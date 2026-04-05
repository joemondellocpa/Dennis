import subprocess
import os


def build():
    src = os.path.join(os.path.dirname(__file__), 'physics_ext.c')
    out = os.path.join(os.path.dirname(__file__), 'physics_ext.so')
    subprocess.run(
        ['gcc', '-O2', '-shared', '-fPIC', '-o', out, src],
        check=True,
    )
    return out


if __name__ == '__main__':
    path = build()
    print(f'Built: {path}')
