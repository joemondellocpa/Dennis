#include <stdint.h>
#include <string.h>

/* Cell type constants — must match CellType enum in cells.py */
#define CELL_AIR   0
#define CELL_STONE 1
#define CELL_SOIL  2
#define CELL_WATER 3
#define CELL_SAND  4
#define CELL_LAVA  5
#define CELL_ICE   6
#define CELL_WOOD  7

/*
 * spread_fluid
 * ------------
 * Process fluid spreading within a single cubic chunk stored as a flat
 * row-major uint8 array of shape (size, size, size).
 *
 * Index formula (matching numpy C order with axes x,y,z):
 *   idx(x,y,z) = x*size*size + y*size + z
 *
 * Rules applied (single pass over all cells):
 *  - Fluid falls to z-1 if that cell is AIR.
 *  - Fluid spreads laterally (±x, ±y at same z) into AIR if it cannot fall.
 *
 * Parameters:
 *   chunk      - pointer to the flat uint8 chunk array (modified in-place)
 *   size       - side length of the chunk (typically 16)
 *   fluid_type - cell type value of the fluid to process (WATER or LAVA)
 *   air_type   - cell type value considered empty (AIR)
 *
 * Returns:
 *   Number of cells changed.
 */
int spread_fluid(uint8_t *chunk, int size, uint8_t fluid_type, uint8_t air_type)
{
    int changed = 0;
    int size2 = size * size;

    /* We work on a copy to avoid order-dependent propagation within one tick. */
    uint8_t *buf = (uint8_t *)__builtin_alloca((size_t)size * size * size);
    memcpy(buf, chunk, (size_t)size * size * size);

#define IDX(x, y, z) ((x)*size2 + (y)*size + (z))

    for (int x = 0; x < size; x++) {
        for (int y = 0; y < size; y++) {
            for (int z = 0; z < size; z++) {
                if (buf[IDX(x, y, z)] != fluid_type)
                    continue;

                /* Try to fall (z - 1) */
                if (z > 0 && buf[IDX(x, y, z - 1)] == air_type) {
                    chunk[IDX(x, y, z - 1)] = fluid_type;
                    chunk[IDX(x, y, z)]     = air_type;
                    changed++;
                    continue;
                }

                /* Try lateral spread — prefer x-1, x+1, y-1, y+1 in order */
                int spread = 0;

                if (!spread && x > 0 && buf[IDX(x - 1, y, z)] == air_type) {
                    chunk[IDX(x - 1, y, z)] = fluid_type;
                    chunk[IDX(x, y, z)]     = air_type;
                    changed++;
                    spread = 1;
                }
                if (!spread && x < size - 1 && buf[IDX(x + 1, y, z)] == air_type) {
                    chunk[IDX(x + 1, y, z)] = fluid_type;
                    chunk[IDX(x, y, z)]     = air_type;
                    changed++;
                    spread = 1;
                }
                if (!spread && y > 0 && buf[IDX(x, y - 1, z)] == air_type) {
                    chunk[IDX(x, y - 1, z)] = fluid_type;
                    chunk[IDX(x, y, z)]     = air_type;
                    changed++;
                    spread = 1;
                }
                if (!spread && y < size - 1 && buf[IDX(x, y + 1, z)] == air_type) {
                    chunk[IDX(x, y + 1, z)] = fluid_type;
                    chunk[IDX(x, y, z)]     = air_type;
                    changed++;
                }
            }
        }
    }

#undef IDX

    return changed;
}
