"""
c_ext — ctypes wrapper around physics_ext.so.

Usage:
    from life_sim.c_ext import spread_fluid
    changed = spread_fluid(chunk_array, size=16,
                           fluid_type=CELL_WATER, air_type=CELL_AIR)

If the shared library has not been compiled yet, call build_ext.build() first.
"""

import ctypes
import os

_lib = None


def _load():
    global _lib
    if _lib is not None:
        return _lib
    so_path = os.path.join(os.path.dirname(__file__), 'physics_ext.so')
    if not os.path.exists(so_path):
        raise RuntimeError(
            "physics_ext.so not found. Run life_sim/c_ext/build_ext.py first."
        )
    _lib = ctypes.CDLL(so_path)
    _lib.spread_fluid.restype = ctypes.c_int
    _lib.spread_fluid.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),  # chunk
        ctypes.c_int,                    # size
        ctypes.c_uint8,                  # fluid_type
        ctypes.c_uint8,                  # air_type
    ]
    return _lib


def spread_fluid(chunk_array, size: int, fluid_type: int, air_type: int) -> int:
    """
    Call the C spread_fluid function on a numpy uint8 chunk array.

    chunk_array must be a numpy array with dtype=uint8 and contiguous C order.
    Returns the number of cells changed.
    """
    import numpy as np
    lib = _load()
    if not chunk_array.flags['C_CONTIGUOUS']:
        chunk_array = np.ascontiguousarray(chunk_array, dtype=np.uint8)
    ptr = chunk_array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
    return lib.spread_fluid(ptr, ctypes.c_int(size),
                            ctypes.c_uint8(fluid_type),
                            ctypes.c_uint8(air_type))
