import curses
import time
from collections import deque

# Cell rendering characters
# key = CellType int value
CELL_CHARS = {
    0: (' ', 0),   # AIR: space, no color
    1: ('#', 7),   # STONE: #, white
    2: ('~', 2),   # SOIL: ~, green
    3: ('W', 4),   # WATER: W, blue
    4: ('.', 7),   # SAND: ., white
    5: ('^', 1),   # LAVA: ^, red
    6: ('*', 6),   # ICE: *, cyan
    7: ('T', 2),   # WOOD: T, green
}

CELL_NAMES = {
    0: 'AIR',
    1: 'STONE',
    2: 'SOIL',
    3: 'WATER',
    4: 'SAND',
    5: 'LAVA',
    6: 'ICE',
    7: 'WOOD',
}

WORLD_W = 1000
WORLD_H = 1000
WORLD_D = 100

MINIMAP_W = 26
MINIMAP_H = 12

HELP_LINES = [
    " KEY BINDINGS ",
    "",
    " Arrow keys      Scroll viewport",
    " +/=             Go up one z-level",
    " -               Go down one z-level",
    " s               Enter selection mode",
    " Enter           Select cell/organism",
    " Esc             Cancel selection",
    " Space           Pause / unpause",
    " >               Increase speed",
    " <               Decrease speed",
    " Tab             Cycle to next organism",
    " Shift+Tab       Cycle to prev organism",
    " h               Toggle this help",
    " S               Species registry",
    " q               Quit",
    "",
    " Press any key to close ",
]


class AsciiUI:
    def __init__(self, world, organism_pool, simulation):
        self.world = world
        self.pool = organism_pool
        self.sim = simulation

        # Viewport state
        self.view_x = 0   # top-left world x of viewport
        self.view_y = 0   # top-left world y of viewport
        self.view_z = 25  # current z-level being shown

        # Selection state
        self.selection_mode = False
        self.cursor_x = 0  # world coords of cursor
        self.cursor_y = 0
        self.selected_organism = None  # Organism or None
        self.selected_cell = None      # (x, y, z, cell_type) or None
        self._tab_org_id: int = -1     # id of last-tabbed-to organism (ID-stable cycling)

        # Simulation speed
        self.ticks_per_frame = 1  # how many ticks to run before re-rendering

        self.stdscr = None
        self.info_panel_width = 30
        self.help_visible = False
        self.species_screen_visible = False
        self._species_scroll = 0

        # FPS tracking — store timestamps of last N frame render completions
        self._frame_times: deque = deque(maxlen=20)
        self._last_render_time: float = 0.0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self):
        """Main entry point — wraps curses.wrapper."""
        curses.wrapper(self._main)

    # ------------------------------------------------------------------
    # Internal main loop
    # ------------------------------------------------------------------

    def _main(self, stdscr):
        self.stdscr = stdscr
        self._setup_colors()
        curses.curs_set(0)
        stdscr.nodelay(True)   # non-blocking input
        stdscr.timeout(50)     # 50 ms timeout for getch

        self._center_on_first_organism()

        while self.sim.running:
            # Process input
            key = stdscr.getch()
            if key != -1:
                quit_requested = self._handle_key(key)
                if quit_requested:
                    break

            # Run simulation ticks if not paused
            if not self.sim.paused:
                for _ in range(self.ticks_per_frame):
                    self.sim.step()

            # Render
            self._render()

    # ------------------------------------------------------------------
    # Color setup
    # ------------------------------------------------------------------

    def _setup_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED,     -1)
        curses.init_pair(2, curses.COLOR_GREEN,   -1)
        curses.init_pair(3, curses.COLOR_YELLOW,  -1)
        curses.init_pair(4, curses.COLOR_BLUE,    -1)
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        curses.init_pair(6, curses.COLOR_CYAN,    -1)
        curses.init_pair(7, curses.COLOR_WHITE,   -1)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def _handle_key(self, key) -> bool:
        """Handle keyboard input. Returns True if quit was requested."""
        h, w = self.stdscr.getmaxyx()
        view_w = w - self.info_panel_width - 1
        view_h = h - 2

        # Help overlay: any key closes it
        if self.help_visible:
            self.help_visible = False
            return False

        # --- Species screen ---
        if key == ord('S'):
            self.species_screen_visible = not self.species_screen_visible
            self._species_scroll = 0
            return False

        # Species screen: Up/Down scroll, any other key closes
        if self.species_screen_visible:
            if key == curses.KEY_UP:
                self._species_scroll = max(0, self._species_scroll - 1)
                return False
            elif key == curses.KEY_DOWN:
                self._species_scroll += 1
                return False
            # Any other key closes the species screen
            self.species_screen_visible = False
            return False

        # --- Quit ---
        if key in (ord('q'), ord('Q')):
            self.sim.running = False
            return True

        # --- Toggle help ---
        if key in (ord('h'), ord('H')):
            self.help_visible = True
            return False

        # --- Pause / unpause ---
        if key == ord(' '):
            self.sim.paused = not self.sim.paused
            return False

        # --- Speed control ---
        if key in (ord('>'), ord('.')):
            self.ticks_per_frame = min(self.ticks_per_frame * 2, 64)
            return False
        if key in (ord('<'), ord(',')):
            self.ticks_per_frame = max(self.ticks_per_frame // 2, 1)
            return False

        # --- Z level ---
        if key in (ord('+'), ord('=')):
            self.view_z = min(self.view_z + 1, WORLD_D - 1)
            return False
        if key == ord('-'):
            self.view_z = max(self.view_z - 1, 0)
            return False

        # --- Tab: cycle through organisms (ID-stable — survives births/deaths) ---
        if key in (ord('\t'), curses.KEY_BTAB):
            living = sorted(self.pool.living(), key=lambda o: o.id)
            if living:
                ids = [o.id for o in living]
                try:
                    current_idx = ids.index(self._tab_org_id)
                except ValueError:
                    current_idx = -1
                if key == curses.KEY_BTAB:
                    new_idx = (current_idx - 1) % len(living)
                else:
                    new_idx = (current_idx + 1) % len(living)
                org = living[new_idx]
                self._tab_org_id = org.id
                self.view_x = max(0, org.state.x - view_w // 2)
                self.view_y = max(0, org.state.y - view_h // 2)
                self.view_z = org.state.z
                self.selected_organism = org
            return False

        # --- Toggle selection mode ---
        if key == ord('s'):
            self.selection_mode = True
            # Place cursor at viewport center
            self.cursor_x = self.view_x + view_w // 2
            self.cursor_y = self.view_y + view_h // 2
            return False

        # --- Escape: cancel selection ---
        if key == 27:  # ESC
            self.selection_mode = False
            self.selected_organism = None
            self.selected_cell = None
            return False

        # --- Enter: confirm selection ---
        if key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            if self.selection_mode:
                self._confirm_selection()
                self.selection_mode = False
            return False

        # --- Arrow keys ---
        if self.selection_mode:
            # Move cursor, scrolling viewport if needed
            if key == curses.KEY_UP:
                self.cursor_y -= 1
                if self.cursor_y < self.view_y:
                    self.view_y = max(self.view_y - 1, 0)
                    self.cursor_y = self.view_y
            elif key == curses.KEY_DOWN:
                self.cursor_y += 1
                if self.cursor_y >= self.view_y + view_h:
                    self.view_y = min(self.view_y + 1, WORLD_H - view_h)
                    self.cursor_y = self.view_y + view_h - 1
            elif key == curses.KEY_LEFT:
                self.cursor_x -= 1
                if self.cursor_x < self.view_x:
                    self.view_x = max(self.view_x - 1, 0)
                    self.cursor_x = self.view_x
            elif key == curses.KEY_RIGHT:
                self.cursor_x += 1
                if self.cursor_x >= self.view_x + view_w:
                    self.view_x = min(self.view_x + 1, WORLD_W - view_w)
                    self.cursor_x = self.view_x + view_w - 1
        else:
            # Scroll viewport
            scroll = 5
            if key == curses.KEY_UP:
                self.view_y = max(self.view_y - scroll, 0)
            elif key == curses.KEY_DOWN:
                self.view_y = min(self.view_y + scroll, WORLD_H - max(view_h, 1))
            elif key == curses.KEY_LEFT:
                self.view_x = max(self.view_x - scroll, 0)
            elif key == curses.KEY_RIGHT:
                self.view_x = min(self.view_x + scroll, WORLD_W - max(view_w, 1))

        return False

    def _confirm_selection(self):
        """Commit whatever is under the cursor as the active selection."""
        cx, cy = self.cursor_x, self.cursor_y
        # Check for organism at cursor position on current z
        for org in self.pool.living():
            if org.state.x == cx and org.state.y == cy and org.state.z == self.view_z:
                self.selected_organism = org
                self.selected_cell = None
                return
        # Otherwise select the cell
        self.selected_organism = None
        cell_type = self.world.get_cell(cx, cy, self.view_z)
        self.selected_cell = (cx, cy, self.view_z, cell_type)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self):
        """Full screen redraw."""
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        view_w = w - self.info_panel_width - 1
        view_h = h - 2  # leave room for status bar

        if view_w > 0 and view_h > 0:
            self._render_world_view(view_w, view_h)

        if self.info_panel_width > 0:
            self._render_info_panel(view_w + 1, view_h)

        self._render_status_bar(h - 1, w)

        if self.help_visible:
            self._render_help_overlay(h, w)

        if self.species_screen_visible:
            self._render_species_screen(h, w)

        # Track frame time for FPS computation
        now = time.time()
        if self._last_render_time > 0:
            self._frame_times.append(now - self._last_render_time)
        self._last_render_time = now

        self.stdscr.refresh()

    def _render_world_view(self, view_w: int, view_h: int):
        """Render the top-down z-slice view."""
        # Build organism position lookup for this z level
        org_at: dict = {}
        for org in self.pool.living():
            if org.state.z == self.view_z:
                org_at[(org.state.x, org.state.y)] = org

        for screen_y in range(view_h):
            world_y = self.view_y + screen_y
            for screen_x in range(view_w):
                world_x = self.view_x + screen_x

                if not (0 <= world_x < WORLD_W and 0 <= world_y < WORLD_H):
                    # Out-of-bounds: draw border character
                    try:
                        self.stdscr.addch(screen_y, screen_x, ' ')
                    except curses.error:
                        pass
                    continue

                # Check for organism first
                if (world_x, world_y) in org_at:
                    org = org_at[(world_x, world_y)]
                    ch = org.display_char
                    color = curses.color_pair(org.display_color_pair)
                    if self.selected_organism and org.id == self.selected_organism.id:
                        color |= curses.A_REVERSE
                else:
                    cell = self.world.get_cell(world_x, world_y, self.view_z)
                    if cell == 0 and self.view_z > 0:  # AIR at current level — look below
                        cell_below = self.world.get_cell(world_x, world_y, self.view_z - 1)
                        if cell_below != 0:  # non-air below — floor reveal
                            ch, color_idx = CELL_CHARS.get(cell_below, ('?', 7))
                            color = (curses.color_pair(color_idx) if color_idx else 0) | curses.A_DIM
                        else:
                            ch, color_idx = CELL_CHARS.get(cell, ('?', 7))  # both levels are AIR
                            color = 0
                    else:
                        ch, color_idx = CELL_CHARS.get(cell, ('?', 7))
                        color = curses.color_pair(color_idx) if color_idx else 0

                # Draw cursor highlight in selection mode
                if self.selection_mode:
                    if world_x == self.cursor_x and world_y == self.cursor_y:
                        # Bright yellow reverse block — always visible regardless of cell type
                        try:
                            self.stdscr.addch(screen_y, screen_x, ch,
                                              curses.color_pair(3) | curses.A_REVERSE | curses.A_BOLD)
                        except curses.error:
                            pass
                        continue
                    elif world_x == self.cursor_x or world_y == self.cursor_y:
                        # Crosshair: dim yellow tint on the cursor row/column
                        color = curses.color_pair(3)

                try:
                    self.stdscr.addch(screen_y, screen_x, ch, color)
                except curses.error:
                    pass

        # Draw a vertical separator between world view and info panel
        h, w = self.stdscr.getmaxyx()
        sep_col = view_w
        for row in range(view_h):
            try:
                self.stdscr.addch(row, sep_col, '|', curses.color_pair(7))
            except curses.error:
                pass

    def _render_info_panel(self, panel_x: int, panel_h: int):
        """Render the right-side info panel."""
        panel_w = self.info_panel_width
        row = 0

        def put(text: str, attr: int = 0):
            nonlocal row
            if row >= panel_h:
                return
            # Truncate to panel width
            line = text[:panel_w]
            try:
                self.stdscr.addstr(row, panel_x, line, attr)
            except curses.error:
                pass
            row += 1

        title_attr = curses.color_pair(3) | curses.A_BOLD

        if self.selected_organism is not None:
            org = self.selected_organism
            put("[ Selected Organism ]", title_attr)
            put("")

            summary = {}
            try:
                summary = org.stats_summary()
            except Exception:
                pass

            for key, val in summary.items():
                line = f" {key}: {val}"
                put(line)

            put("")
            put(f" Pos: ({org.state.x}, {org.state.y}, {org.state.z})")
            put(f" Char: {org.display_char}  Color: {org.display_color_pair}")
            put("")
            put(" Esc: deselect", curses.color_pair(7))

        elif self.selected_cell is not None:
            cx, cy, cz, cell_type = self.selected_cell
            cell_name = CELL_NAMES.get(cell_type, f"UNKNOWN({cell_type})")
            put("[ Selected Cell ]", title_attr)
            put("")
            put(f" Type: {cell_name}")
            put(f" X:    {cx}")
            put(f" Y:    {cy}")
            put(f" Z:    {cz}")
            put("")
            put(" Esc: deselect", curses.color_pair(7))

        else:
            put("[ Info Panel ]", title_attr)
            put("")
            if self.selection_mode:
                put("[ Selection Mode ]", curses.color_pair(3) | curses.A_BOLD)
                put(f" ({self.cursor_x}, {self.cursor_y}, {self.view_z})")
                put("")
                # Live preview of what's under the cursor
                cx, cy = self.cursor_x, self.cursor_y
                under_org = None
                for org in self.pool.living():
                    if (org.state.x == cx and org.state.y == cy
                            and org.state.z == self.view_z):
                        under_org = org
                        break
                if under_org:
                    put(" Under cursor:", curses.color_pair(6))
                    put(f"  Organism {hex(under_org.id)[-6:]}")
                    put(f"  Age:  {under_org.state.age}")
                    put(f"  Cal:  {under_org.state.calories:.0f}")
                    put(f"  Size: {under_org.body.total_cells}")
                else:
                    ct = self.world.get_cell(cx, cy, self.view_z)
                    cell_name = CELL_NAMES.get(ct, '?')
                    put(" Under cursor:", curses.color_pair(6))
                    put(f"  {cell_name}")
                put("")
                put(" Enter: confirm")
                put(" Esc:   cancel")
            else:
                put(" Arrow keys: scroll")
                put(" s:          select")
                put(" Tab:        next org")
                put(" Space:      pause")
                put(" +/-:        z level")
                put(" >/<:        speed")
                put(" h:          help")
                put(" q:          quit")

        self._render_minimap(panel_x, panel_h)

    def _render_status_bar(self, row: int, width: int):
        """Render bottom status bar."""
        h, _ = self.stdscr.getmaxyx()
        if row < 0 or row >= h:
            return

        # Compute FPS
        fps_str = "FPS:--"
        if len(self._frame_times) >= 2:
            avg_dt = sum(self._frame_times) / len(self._frame_times)
            if avg_dt > 0:
                fps = 1.0 / avg_dt
                fps_str = f"FPS:{fps:.0f}"

        # Org count
        try:
            org_count = len(list(self.pool.living()))
        except Exception:
            org_count = 0

        pause_str = "[PAUSED]" if self.sim.paused else "       "
        speed_str = f"x{self.ticks_per_frame}"

        z_str = (f" Z:{self.view_z}(f:{self.view_z-1})  "
                 if self.view_z > 0 else f" Z:{self.view_z}       ")
        status = (
            z_str
            + f"Tick:{self.sim.tick_count:<7}  "
            f"Orgs:{org_count:<5}  "
            f"{fps_str}  "
            f"{pause_str}  "
            f"Spd:{speed_str}  "
            f"q=quit +/-=z h=help"
        )

        # Truncate to terminal width (leave last col for safety)
        status = status[: width - 1]

        attr = curses.color_pair(3) | curses.A_BOLD
        try:
            self.stdscr.addstr(row, 0, status, attr)
        except curses.error:
            pass

    def _render_help_overlay(self, h: int, w: int):
        """Render a centered help overlay with key bindings."""
        box_h = len(HELP_LINES) + 2
        box_w = max(len(l) for l in HELP_LINES) + 4

        start_y = max((h - box_h) // 2, 0)
        start_x = max((w - box_w) // 2, 0)

        attr_box   = curses.color_pair(7) | curses.A_BOLD
        attr_title = curses.color_pair(3) | curses.A_BOLD
        attr_text  = curses.color_pair(7)

        # Top border
        top_line = "+" + "-" * (box_w - 2) + "+"
        try:
            self.stdscr.addstr(start_y, start_x, top_line[:w - start_x], attr_box)
        except curses.error:
            pass

        for i, line in enumerate(HELP_LINES):
            y = start_y + 1 + i
            if y >= h:
                break
            padded = "| " + line.ljust(box_w - 4) + " |"
            attr = attr_title if i == 0 else attr_text
            try:
                self.stdscr.addstr(y, start_x, padded[:w - start_x], attr)
            except curses.error:
                pass

        # Bottom border
        bot_y = start_y + box_h - 1
        if bot_y < h:
            bot_line = "+" + "-" * (box_w - 2) + "+"
            try:
                self.stdscr.addstr(bot_y, start_x, bot_line[:w - start_x], attr_box)
            except curses.error:
                pass

    def _render_species_screen(self, h: int, w: int):
        """Render a full-screen species registry overlay."""
        attr_title   = curses.color_pair(3) | curses.A_BOLD
        attr_header  = curses.color_pair(7) | curses.A_BOLD
        attr_alive   = curses.color_pair(2)
        attr_extinct = curses.color_pair(1) | curses.A_DIM
        attr_bg      = curses.color_pair(7)

        # Draw a full-screen dark background by blanking each row
        for row in range(h):
            try:
                self.stdscr.addstr(row, 0, ' ' * (w - 1), attr_bg)
            except curses.error:
                pass

        # Title bar
        title = "SPECIES REGISTRY  [S to close]"
        try:
            self.stdscr.addstr(0, 0, title.ljust(w - 1), attr_title)
        except curses.error:
            pass

        # Column headers
        header = f" {'ID':<6}  {'Pop':<5}  {'Extinct?':<14}  {'Age':<7}  Key Genes"
        try:
            self.stdscr.addstr(1, 0, header[:w - 1], attr_header)
        except curses.error:
            pass

        # Separator line
        try:
            self.stdscr.addstr(2, 0, '-' * (w - 1), attr_header)
        except curses.error:
            pass

        # Fetch species data
        species_list = []
        try:
            species_list = self.sim.get_species_stats()
        except Exception:
            try:
                self.stdscr.addstr(3, 0, " (species data unavailable)", attr_extinct)
            except curses.error:
                pass
            return

        # Clamp scroll
        max_rows = h - 4  # rows available for species data (rows 3..h-2, leave status)
        max_scroll = max(0, len(species_list) - max_rows)
        self._species_scroll = min(self._species_scroll, max_scroll)

        visible = species_list[self._species_scroll: self._species_scroll + max_rows]

        for i, sp in enumerate(visible):
            row = 3 + i
            if row >= h - 1:
                break

            sid      = sp['species_id']
            pop      = sp['population']
            extinct  = sp['extinct']
            ext_tick = sp['extinct_tick']
            first    = sp['first_tick']
            genome   = sp['genome']

            # Current tick for age computation
            try:
                cur_tick = self.sim.tick_count
            except Exception:
                cur_tick = 0
            age = cur_tick - first

            # ID: show hex last 4 digits
            id_str = f"#{sid & 0xFFFF:04x}"

            # Extinct field
            if extinct:
                ext_str = f"EXTINCT:{ext_tick}" if ext_tick is not None else "EXTINCT"
            else:
                ext_str = "alive"

            # Key genes
            try:
                sz  = genome.get_dominant_allele('size')
                mt  = genome.get_dominant_allele('metabolism_rate')
                dig = 'Y' if genome.get_dominant_allele('can_dig')  > 127 else 'N'
                sw  = 'Y' if genome.get_dominant_allele('can_swim') > 127 else 'N'
                rm  = genome.get_dominant_allele('reproduction_mode')
                sx  = 'S' if rm >= 128 else 'A'
                genes_str = f"sz={sz:<3} mt={mt:<3} dig={dig} sw={sw} sx={sx}"
            except Exception:
                genes_str = "(genome unavailable)"

            line = f" {id_str:<6}  {pop:<5}  {ext_str:<14}  t:{age:<5}  {genes_str}"
            attr = attr_extinct if extinct else attr_alive
            try:
                self.stdscr.addstr(row, 0, line[:w - 1], attr)
            except curses.error:
                pass

        # Footer: scroll hint
        footer_row = h - 1
        total = len(species_list)
        showing_end = min(self._species_scroll + max_rows, total)
        footer = (f" Showing {self._species_scroll + 1}-{showing_end} of {total} species"
                  "  |  Up/Down to scroll  |  any other key to close")
        try:
            self.stdscr.addstr(footer_row, 0, footer[:w - 1], attr_title)
        except curses.error:
            pass

    # ------------------------------------------------------------------
    # Initial viewport centering
    # ------------------------------------------------------------------

    def _center_on_first_organism(self):
        """Center the viewport on the first living organism at startup."""
        h, w = self.stdscr.getmaxyx()
        view_w = w - self.info_panel_width - 1
        view_h = h - 2
        living = self.pool.living()
        if living:
            org = living[0]
            self.view_x = max(0, org.state.x - view_w // 2)
            self.view_y = max(0, org.state.y - view_h // 2)
            self.view_z = org.state.z
        else:
            self.view_x = max(0, WORLD_W // 2 - view_w // 2)
            self.view_y = max(0, WORLD_H // 2 - view_h // 2)
            self.view_z = 26

    # ------------------------------------------------------------------
    # Minimap
    # ------------------------------------------------------------------

    def _render_minimap(self, panel_x: int, panel_h: int):
        """Render a small overview map at the bottom of the info panel."""
        map_start_row = panel_h - MINIMAP_H - 1
        if map_start_row < 1:
            return

        scale_x = WORLD_W / MINIMAP_W
        scale_y = WORLD_H / MINIMAP_H

        # Build grid of (char, attr) — terrain layer
        grid_ch   = [[' '] * MINIMAP_W for _ in range(MINIMAP_H)]
        grid_attr = [[0]   * MINIMAP_W for _ in range(MINIMAP_H)]

        for my in range(MINIMAP_H):
            for mx in range(MINIMAP_W):
                wx = int(mx * scale_x)
                wy = int(my * scale_y)
                cell = self.world.get_cell(wx, wy, self.view_z)
                ch, color_idx = CELL_CHARS.get(cell, (' ', 0))
                grid_ch[my][mx] = ch
                grid_attr[my][mx] = curses.color_pair(color_idx) if color_idx else 0

        # Organism dots (cap at 200 to stay fast)
        org_attr = curses.color_pair(3)  # yellow
        for org in self.pool.living()[:200]:
            mx = min(MINIMAP_W - 1, int(org.state.x / scale_x))
            my = min(MINIMAP_H - 1, int(org.state.y / scale_y))
            grid_ch[my][mx] = '*'
            grid_attr[my][mx] = org_attr

        # Viewport rectangle (drawn on top of terrain/orgs)
        h, w = self.stdscr.getmaxyx()
        vw = w - self.info_panel_width - 1
        vh = h - 2
        vp_x0 = max(0, min(int(self.view_x / scale_x), MINIMAP_W - 1))
        vp_y0 = max(0, min(int(self.view_y / scale_y), MINIMAP_H - 1))
        vp_x1 = max(0, min(int((self.view_x + vw) / scale_x), MINIMAP_W - 1))
        vp_y1 = max(0, min(int((self.view_y + vh) / scale_y), MINIMAP_H - 1))
        vp_attr = curses.color_pair(7) | curses.A_BOLD

        if vp_x0 == vp_x1 or vp_y0 == vp_y1:
            grid_ch[vp_y0][vp_x0] = '+'
            grid_attr[vp_y0][vp_x0] = vp_attr
        else:
            for mx in range(vp_x0, vp_x1 + 1):
                grid_ch[vp_y0][mx] = '-'; grid_attr[vp_y0][mx] = vp_attr
                grid_ch[vp_y1][mx] = '-'; grid_attr[vp_y1][mx] = vp_attr
            for my in range(vp_y0, vp_y1 + 1):
                grid_ch[my][vp_x0] = '|'; grid_attr[my][vp_x0] = vp_attr
                grid_ch[my][vp_x1] = '|'; grid_attr[my][vp_x1] = vp_attr
            for corner_y, corner_x in [(vp_y0, vp_x0), (vp_y0, vp_x1),
                                        (vp_y1, vp_x0), (vp_y1, vp_x1)]:
                grid_ch[corner_y][corner_x] = '+'
                grid_attr[corner_y][corner_x] = vp_attr

        # Title
        title = f"[Map z={self.view_z}]"
        try:
            self.stdscr.addstr(map_start_row, panel_x,
                               title[:self.info_panel_width],
                               curses.color_pair(3) | curses.A_BOLD)
        except curses.error:
            pass

        # Draw grid rows
        for my in range(MINIMAP_H):
            screen_row = map_start_row + 1 + my
            if screen_row >= panel_h:
                break
            for mx in range(MINIMAP_W):
                try:
                    self.stdscr.addch(screen_row, panel_x + mx,
                                      grid_ch[my][mx], grid_attr[my][mx])
                except curses.error:
                    pass
