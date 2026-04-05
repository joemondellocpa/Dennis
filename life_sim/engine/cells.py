from enum import IntEnum


class CellType(IntEnum):
    AIR = 0
    STONE = 1
    SOIL = 2
    WATER = 3
    SAND = 4
    LAVA = 5
    ICE = 6
    WOOD = 7


# Properties per cell type
CELL_PROPS = {
    CellType.AIR:   dict(density=0,    passable=True,  fluid=False, diggable=False, flammable=False, calorie_value=0,  light_pass=True,  heat_pass=True),
    CellType.STONE: dict(density=2700, passable=False, fluid=False, diggable=True,  flammable=False, calorie_value=0,  light_pass=False, heat_pass=False),
    CellType.SOIL:  dict(density=1500, passable=False, fluid=False, diggable=True,  flammable=False, calorie_value=1,  light_pass=False, heat_pass=False),
    CellType.WATER: dict(density=1000, passable=True,  fluid=True,  diggable=False, flammable=False, calorie_value=0,  light_pass=True,  heat_pass=True),
    CellType.SAND:  dict(density=1600, passable=False, fluid=False, diggable=True,  flammable=False, calorie_value=0,  light_pass=False, heat_pass=False),
    CellType.LAVA:  dict(density=2800, passable=False, fluid=True,  diggable=False, flammable=False, calorie_value=0,  light_pass=False, heat_pass=True),
    CellType.ICE:   dict(density=917,  passable=False, fluid=False, diggable=True,  flammable=False, calorie_value=0,  light_pass=True,  heat_pass=False),
    CellType.WOOD:  dict(density=600,  passable=False, fluid=False, diggable=True,  flammable=True,  calorie_value=10, light_pass=False, heat_pass=False),
}


def cell_is_passable(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['passable']


def cell_density(cell_type: int) -> int:
    return CELL_PROPS[CellType(cell_type)]['density']


def cell_is_fluid(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['fluid']


def cell_is_diggable(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['diggable']


def cell_is_flammable(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['flammable']


def cell_calorie_value(cell_type: int) -> int:
    return CELL_PROPS[CellType(cell_type)]['calorie_value']


def cell_light_pass(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['light_pass']


def cell_heat_pass(cell_type: int) -> bool:
    return CELL_PROPS[CellType(cell_type)]['heat_pass']
