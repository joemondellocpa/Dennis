#!/usr/bin/env python3
"""
Dennis Life Simulator — entry point.

Usage:
    python -m life_sim.main [--seed N] [--no-build-ext]
"""
import argparse
import sys
import os


def build_c_extensions():
    """Compile C extensions if not already built."""
    ext_dir = os.path.join(os.path.dirname(__file__), 'c_ext')
    so_path = os.path.join(ext_dir, 'physics_ext.so')
    if not os.path.exists(so_path):
        print("Building C extensions...")
        sys.path.insert(0, ext_dir)
        try:
            from c_ext.build_ext import build
            build()
            print("C extensions built successfully.")
        except Exception as e:
            print(f"Warning: C extension build failed ({e}). Falling back to pure Python.")


def main():
    parser = argparse.ArgumentParser(description='Dennis Life Simulator')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')
    parser.add_argument('--no-build-ext', action='store_true', help='Skip C extension build')
    parser.add_argument('--headless', action='store_true',
                        help='Run headless (no UI) for N ticks then exit')
    parser.add_argument('--ticks', type=int, default=1000,
                        help='Ticks to run in headless mode (default: 1000)')
    args = parser.parse_args()

    if not args.no_build_ext:
        build_c_extensions()

    from life_sim.engine.simulation import Simulation

    print(f"Initializing simulation (seed={args.seed})...")
    sim = Simulation(seed=args.seed)
    print(f"World generated. {sim.pool.count()} starter organisms placed.")

    if args.headless:
        print(f"Running {args.ticks} ticks headless...")
        for i in range(args.ticks):
            sim.step()
            if i % 100 == 0:
                stats = sim.get_stats()
                print(f"  Tick {stats['tick']:5d} | Organisms: {stats['organisms']:5d}")
        print("Done.")
        return

    # Launch ASCII UI
    from life_sim.ui.ascii_ui import AsciiUI
    ui = AsciiUI(sim.world, sim.pool, sim)
    ui.run()


if __name__ == '__main__':
    main()
