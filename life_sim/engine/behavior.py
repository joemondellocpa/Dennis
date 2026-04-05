import json, os, copy, random
from pathlib import Path

BEHAVIORS_DIR = Path(__file__).parent.parent / 'behaviors'

class BehaviorDef:
    """Loaded behavior definition from JSON."""
    __slots__ = ['id', 'name', 'priority', 'condition_type', 'condition_param',
                 'action_type', 'speed_multiplier', 'calorie_multiplier', 'action_param']

    def __init__(self, data: dict):
        self.id = data['id']
        self.name = data['name']
        self.priority = data['priority']
        self.condition_type = data['condition']['type']
        self.condition_param = data['condition'].get('param', 0)
        self.action_type = data['action']['type']
        self.speed_multiplier = data['action'].get('speed_multiplier', 1.0)
        self.calorie_multiplier = data['action'].get('calorie_multiplier', 1.0)
        self.action_param = data['action'].get('param', 0)

# Global registry: id -> BehaviorDef
_behavior_registry: dict[str, BehaviorDef] = {}
_behavior_list: list[BehaviorDef] = []  # ordered by id for slot indexing

def load_all_behaviors():
    """Load all JSON files from behaviors/ dir into registry."""
    global _behavior_list
    for path in sorted(BEHAVIORS_DIR.glob('*.json')):
        with open(path) as f:
            data = json.load(f)
        b = BehaviorDef(data)
        _behavior_registry[b.id] = b
    _behavior_list = sorted(_behavior_registry.values(), key=lambda b: b.id)

def get_behavior_by_index(idx: int) -> BehaviorDef | None:
    if 0 <= idx < len(_behavior_list):
        return _behavior_list[idx]
    return None

def get_behavior_count() -> int:
    return len(_behavior_list)

def mutate_behavior_file(behavior_id: str) -> str:
    """
    Copy a behavior JSON file with slightly tweaked numeric parameters.
    Returns the new behavior id.
    Saves new file to behaviors/ dir.
    """
    if behavior_id not in _behavior_registry:
        return behavior_id

    # Load original JSON
    src_path = BEHAVIORS_DIR / f"{behavior_id}.json"
    if not src_path.exists():
        return behavior_id

    with open(src_path) as f:
        data = json.load(f)

    # Tweak condition param ±20%
    if 'param' in data['condition']:
        val = data['condition']['param']
        data['condition']['param'] = max(1, val * random.uniform(0.8, 1.2))

    # Tweak action speed/calorie multipliers ±10%
    for key in ('speed_multiplier', 'calorie_multiplier'):
        if key in data['action']:
            data['action'][key] = max(0.1, data['action'][key] * random.uniform(0.9, 1.1))

    # New unique id
    new_id = f"{behavior_id}_mut_{random.randint(1000,9999)}"
    data['id'] = new_id
    data['name'] = f"{data['name']} (variant)"

    # Save
    new_path = BEHAVIORS_DIR / f"{new_id}.json"
    with open(new_path, 'w') as f:
        json.dump(data, f, indent=2)

    # Register in memory
    b = BehaviorDef(data)
    _behavior_registry[new_id] = b
    _behavior_list.append(b)

    return new_id


class BehaviorEvaluator:
    """
    Evaluates and executes behaviors for one organism per tick.
    Stateless — takes world snapshot inputs, returns action to take.
    """

    def evaluate(self, organism_state, body_plan, genome, world_context: dict) -> dict | None:
        """
        world_context has:
            calories: float
            calories_max: float
            nearest_threat_dist: float (inf if none)
            nearest_food_dist: float (inf if none)
            nearest_food_pos: (x,y,z) or None
            nearest_mate_dist: float
            nearest_mate_id: int or None
            in_water: bool
            has_lung: bool
            has_gill: bool
            age: int
            maturity_ticks: int

        Returns action dict: {'type': str, 'speed_multiplier': float, ...} or None
        """
        # Get organism's behavior slots from genome
        from .genetics import Genome
        slots = []
        for i in range(4):
            slot_val = genome.get_dominant_allele(f'behavior_slot_{i}')
            b = get_behavior_by_index(slot_val % max(1, get_behavior_count()))
            if b:
                slots.append(b)

        # Sort by priority descending
        slots.sort(key=lambda b: b.priority, reverse=True)

        for behavior in slots:
            if self._check_condition(behavior, world_context):
                return {
                    'behavior_name': behavior.name,
                    'action_type': behavior.action_type,
                    'speed_multiplier': behavior.speed_multiplier,
                    'calorie_multiplier': behavior.calorie_multiplier,
                    'action_param': behavior.action_param,
                    'target': world_context.get('nearest_food_pos') if behavior.action_type in ('approach', 'eat', 'dig') else None,
                }
        return None

    def _check_condition(self, behavior: BehaviorDef, ctx: dict) -> bool:
        ct = behavior.condition_type
        p = behavior.condition_param
        if ct == 'always':
            return True
        elif ct == 'threat_nearby':
            return ctx['nearest_threat_dist'] <= p
        elif ct == 'food_nearby':
            return ctx['nearest_food_dist'] <= p
        elif ct == 'calories_below':
            ratio = ctx['calories'] / max(1, ctx['calories_max'])
            return ratio < p
        elif ct == 'in_wrong_medium':
            # organism in water but has lung, or in air but has gill
            return (ctx['in_water'] and ctx['has_lung']) or (not ctx['in_water'] and ctx['has_gill'])
        elif ct == 'mate_nearby':
            return ctx['nearest_mate_dist'] <= p
        elif ct == 'prey_nearby':
            return ctx.get('nearest_prey_dist', float('inf')) <= p
        return False
