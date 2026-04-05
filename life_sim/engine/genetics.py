"""
genetics.py — Genome and BodyPlan for the life simulator.

Each gene is a pair of alleles (a, b), each an integer 0..255.
Dominance rule: the higher value wins. Phenotype = dominant / 255.0.
"""

import random
from typing import Dict, Optional, Tuple


class Genome:
    """Stores a full set of gene allele pairs for one organism."""

    # All gene names, in a stable order for crossover indexing.
    GENES = [
        # Physical
        'size',
        'color_r', 'color_g', 'color_b',
        # Capabilities (dominant allele > 127 means the capability is present)
        'can_dig',
        'can_swim',
        'can_climb',
        'can_float',
        # Metabolism
        'metabolism_rate',
        'calorie_efficiency',
        # Reproduction
        'reproduction_mode',   # <128 dominant = asexual, >=128 = sexual
        'maturity_ticks',
        'reproduction_cost',
        # Senses
        'vision_range',
        'smell_range',
        # Body plan ratios (normalized 0..1)
        'muscle_ratio',
        'digestive_ratio',
        'brain_ratio',
        'shell_ratio',
        'lung_ratio',          # dominant > 128 = lung (land), <= 128 = gill (water)
        # Behavior slots (index into behavior registry)
        'behavior_slot_0',
        'behavior_slot_1',
        'behavior_slot_2',
        'behavior_slot_3',
    ]

    # Pre-build an index for fast lookup.
    _GENE_INDEX: Dict[str, int] = {name: i for i, name in enumerate(GENES)}

    __slots__ = ['_alleles']

    def __init__(self, alleles: Optional[Dict[str, Tuple[int, int]]] = None):
        """
        Parameters
        ----------
        alleles : dict mapping gene_name -> (allele_a, allele_b), optional.
                  Any missing genes are filled with a random pair.
                  Pass None to generate a fully random genome.
        """
        if alleles is None:
            self._alleles: Dict[str, Tuple[int, int]] = {
                gene: (random.randint(0, 255), random.randint(0, 255))
                for gene in Genome.GENES
            }
        else:
            self._alleles = {}
            for gene in Genome.GENES:
                if gene in alleles:
                    a, b = alleles[gene]
                    self._alleles[gene] = (int(a) & 0xFF, int(b) & 0xFF)
                else:
                    self._alleles[gene] = (
                        random.randint(0, 255),
                        random.randint(0, 255),
                    )

    # ------------------------------------------------------------------
    # Core accessors
    # ------------------------------------------------------------------

    def get_dominant_allele(self, gene_name: str) -> int:
        """Return the dominant allele value (0..255).

        Dominance rule: the higher value is dominant.
        If both alleles are equal, that value is returned directly.
        """
        a, b = self._alleles[gene_name]
        return a if a >= b else b

    def phenotype(self, gene_name: str) -> float:
        """Return the normalized phenotype in [0.0, 1.0]."""
        return self.get_dominant_allele(gene_name) / 255.0

    def get_alleles(self, gene_name: str) -> Tuple[int, int]:
        """Return the raw (allele_a, allele_b) tuple."""
        return self._alleles[gene_name]

    # ------------------------------------------------------------------
    # Reproduction factories
    # ------------------------------------------------------------------

    @staticmethod
    def random_genome() -> 'Genome':
        """Generate a fully random genome suitable for a starter organism."""
        return Genome()

    @staticmethod
    def sexual_reproduction(
        parent_a: 'Genome',
        parent_b: 'Genome',
        mutation_rate: float = 0.05,
    ) -> 'Genome':
        """Combine two genomes with per-gene crossover and per-allele mutation.

        For each gene:
          - child allele_a is drawn randomly from one allele of parent_a
          - child allele_b is drawn randomly from one allele of parent_b
          - each resulting allele is independently mutated with *mutation_rate*
            probability (replaced by a fresh random byte)
        """
        child_alleles: Dict[str, Tuple[int, int]] = {}

        for gene in Genome.GENES:
            pa = parent_a._alleles[gene]
            pb = parent_b._alleles[gene]

            # Each parent contributes one of their two alleles at random.
            allele_a = random.choice(pa)
            allele_b = random.choice(pb)

            # Mutation
            if random.random() < mutation_rate:
                allele_a = random.randint(0, 255)
            if random.random() < mutation_rate:
                allele_b = random.randint(0, 255)

            child_alleles[gene] = (allele_a, allele_b)

        return Genome(child_alleles)

    @staticmethod
    def asexual_reproduction(
        parent: 'Genome',
        mutation_rate: float = 0.02,
    ) -> 'Genome':
        """Copy the parent genome with a low per-allele mutation chance."""
        child_alleles: Dict[str, Tuple[int, int]] = {}

        for gene in Genome.GENES:
            a, b = parent._alleles[gene]

            if random.random() < mutation_rate:
                a = random.randint(0, 255)
            if random.random() < mutation_rate:
                b = random.randint(0, 255)

            child_alleles[gene] = (a, b)

        return Genome(child_alleles)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        summary = {g: self._alleles[g] for g in Genome.GENES[:6]}
        return f"Genome({summary!r}, ...)"


# ---------------------------------------------------------------------------
# BodyPlan
# ---------------------------------------------------------------------------

class BodyPlan:
    """Physical structure derived from a genome.

    All values are computed once at construction and are read-only thereafter.
    """

    __slots__ = [
        'total_cells',
        'muscle',
        'digestive',
        'brain',
        'shell',
        'lung',
        'calorie_capacity',
        'calorie_cost_per_tick',
        'brain_capacity',
        'has_lung',
        'has_gill',
    ]

    def __init__(self, genome: Genome):
        # ------------------------------------------------------------------
        # Total cell count (1..10)
        # ------------------------------------------------------------------
        total = max(1, int(genome.phenotype('size') * 10))
        self.total_cells: int = total

        # ------------------------------------------------------------------
        # Organ-ratio phenotypes (each 0..1)
        # ------------------------------------------------------------------
        muscle_r    = genome.phenotype('muscle_ratio')
        digestive_r = genome.phenotype('digestive_ratio')
        brain_r     = genome.phenotype('brain_ratio')
        shell_r     = genome.phenotype('shell_ratio')
        lung_r      = genome.phenotype('lung_ratio')

        ratio_sum = muscle_r + digestive_r + brain_r + shell_r + lung_r

        if ratio_sum == 0.0:
            # Degenerate genome — distribute evenly.
            muscle_r = digestive_r = brain_r = shell_r = lung_r = 0.2
            ratio_sum = 1.0

        # Distribute total_cells proportionally, ensuring each organ >= 0.
        scale = total / ratio_sum
        self.muscle:    int = max(0, int(muscle_r    * scale))
        self.digestive: int = max(0, int(digestive_r * scale))
        self.brain:     int = max(0, int(brain_r     * scale))
        self.shell:     int = max(0, int(shell_r     * scale))

        # Lung gets the remainder so the cell count stays exact.
        self.lung: int = max(
            0,
            total - self.muscle - self.digestive - self.brain - self.shell,
        )

        # ------------------------------------------------------------------
        # Derived stats
        # ------------------------------------------------------------------
        # brain_capacity: limits how many behavior slots are active.
        self.brain_capacity: int = self.brain * 10

        # calorie_capacity: larger organisms store more energy.
        self.calorie_capacity: float = float(total * 20)

        # calorie_cost_per_tick: baseline energy burn.
        metabolism_rate_norm = genome.phenotype('metabolism_rate')
        self.calorie_cost_per_tick: float = total * metabolism_rate_norm * 0.5

        # Respiratory type
        self.has_lung: bool = genome.get_dominant_allele('lung_ratio') > 128
        self.has_gill: bool = not self.has_lung

    def __repr__(self) -> str:
        return (
            f"BodyPlan(cells={self.total_cells}, muscle={self.muscle}, "
            f"brain={self.brain}, cap={self.calorie_capacity:.0f}, "
            f"{'lung' if self.has_lung else 'gill'})"
        )
