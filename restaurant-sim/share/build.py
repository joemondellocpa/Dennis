"""Bundle the game into one self-contained page for publishing as a shareable link.
Usage: python3 share/build.py <output.html>   (run from restaurant-sim/)"""
import re, sys, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
html = (root / 'index.html').read_text()
body = re.search(r'<body>(.*)</body>', html, re.S).group(1)
body = re.sub(r'<script src="([^"]+)"></script>', lambda m: '<script>\n' + (root / m.group(1)).read_text().replace('</script', '<\\/script') + '\n</script>', body)
css = (root / 'css/style.css').read_text()
extra = ':root { color-scheme: dark; }\nhtml, body { height: 100%; }\n'
out = '<title>Non-Shitty Restaurant Tycoon</title>\n<style>\n' + css + extra + '</style>\n' + body
pathlib.Path(sys.argv[1]).write_text(out)
print(len(out), 'bytes')
