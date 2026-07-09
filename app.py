#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

"""App."""

from typing import Tuple, List, Callable, Any, Union
import builtins
import platform
import sys
import os
import locale
import time
import json
import threading
import subprocess
import wx
from sgfmill import sgf, sgf_moves, boards as sgf_board

builtins.__dict__["_"] = wx.GetTranslation

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT_DIR,  "resources")

SYSTEM = platform.system()
IS_WINDOWS = SYSTEM == "Windows"
IS_MAC = SYSTEM == "Darwin"
IS_FROZEN = getattr(sys, "frozen", False)


def format_float(val: float, precision: int) -> str:
    """Format float respecting locale."""
    return locale.format_string(f"%.{precision}f", val)


def parse_float(val: str, precision: int) -> float:
    """Parse float respecting locale."""
    return round(locale.atof(val), precision)


def polyfit(x: List[float], y: List[float], degree: int) -> List[float]:
    """Fit points to a polynomial."""
    x_mat = [[xi ** d for d in range(degree, -1, -1)]
             for xi in x]
    xt_mat = [[x_mat[r][c] for r in range(len(x_mat))]
              for c in range(len(x_mat[0]))]
    xtx_mat = [[sum(xt_mat[r][i] * x_mat[i][c] for i in range(len(x_mat)))
                for c in range(len(x_mat[0]))]
               for r in range(len(xt_mat))]
    xty_mat = [sum(xt_mat[r][i] * y[i] for i in range(len(y)))
               for r in range(len(xt_mat))]
    n = len(xtx_mat)
    for i in range(n):
        for j in range(i + 1, n):
            factor = xtx_mat[j][i] / xtx_mat[i][i]
            for k in range(i, n):
                xtx_mat[j][k] -= factor * xtx_mat[i][k]
            xty_mat[j] -= factor * xty_mat[i]
    coef = [0.0] * n
    for i in range(n - 1, -1, -1):
        total = sum(xtx_mat[i][j] * coef[j] for j in range(i + 1, n))
        coef[i] = (xty_mat[i] - total) / xtx_mat[i][i]
    return coef


class Analyzer:
    """Analyzer class."""

    def __init__(self, log: Callable[[str], None],
                 progress: Callable[[float], None],
                 finish: Callable[[], None],
                 katago_path: str,
                 config_path: str,
                 model_path: str,
                 init_moves: List[Tuple[str, str]],
                 game_moves: List[Tuple[str, str]],
                 move_colour: str,
                 moves: List[str],
                 min_weight: float,
                 max_radius: float,
                 komi: Union[float, None]) -> None:
        """Construct analyzer."""
        self.log = log
        self.progress = progress
        self.finish = finish
        self.init_moves = init_moves
        self.game_moves = game_moves
        self.colour = move_colour
        self.moves = moves
        self.min_weight = min_weight
        self.max_radius = max_radius
        self.komi = komi
        self.weight = self.min_weight * (2 + len(moves))
        if komi is not None:
            self.weight -= min_weight * 2
        self.weight_done = 0
        self.target_weight = self.min_weight if komi is None else 0
        self.cur_weight = 0.0
        self.aborted = False
        self.command_lock = threading.Lock()
        self.analysis_cond = threading.Condition()
        self.analysis_results = []
        self.analysis_exit = False
        self.katago = None
        self.katago_path = katago_path
        self.config_path = config_path
        self.model_path = model_path
        self.thread = threading.Thread(target=self.run, name="AnalysisThread")
        self.thread.start()

    def run(self) -> None:
        """Execute analysis."""
        try:
            self.log(_("Launching KataGo..."))
            self.launch_katago()
            assert self.katago is not None
            ver = self.get_version()
            time.sleep(0.5)
            self.log(_("KataGo %s is ready") % ver)
            self.progress(0)

            if self.komi is not None:
                self.log(_("Using provided komi: %s") %
                         format_float(self.komi, 1))
                komi = self.komi
            else:
                self.log(_("Calculating komi..."))
                komi = self.calc_komi()
                self.log(_("Komi: %s") % format_float(komi, 1))

            final_results = []

            for move_idx, move in enumerate(self.moves):
                self.log(_("Analyzing move %s...") % move)
                res, radius, visits, pv = self.analyze_move(move_idx, komi)
                self.log(
                    _("Result for %s: %s (radius: %s visits %d)") %
                    (move, format_float(res * 100, 3),
                     format_float(radius * 100, 3), visits)
                )
                self.log(f"PV: {pv}")
                final_results.append((res, radius))

            ret = self.katago_exit()
            if ret != 0:
                raise RuntimeError(_("KataGo exited with code %d") % ret)
            self.katago = None
            self.progress(1.0)
            self.log(_("Done"))
            self.log("")
            self.log(_("Results (higher is better):"))
            for move, (res, radius) in zip(self.moves, final_results):
                self.log(_("%s: %s (radius %s)") %
                         (move, format_float(res * 100, 3),
                          format_float(radius * 100, 3)))
        except Exception as e:
            self.log(_("Error: %s") % e)
            raise
        finally:
            self.katago_terminate()
            self.finish()

    def launch_katago(self) -> None:
        """Launch katago."""
        if IS_WINDOWS:
            flags = subprocess.CREATE_NO_WINDOW  # type: ignore
        else:
            flags = 0
        process = subprocess.Popen(
            [
                self.katago_path,
                "analysis",
                "-model", self.model_path,
                "-config", self.config_path,
                "-override-config",
                "reportAnalysisWinratesAs=BLACK, "
                "numSearchThreads=1, "
                "useNoisePruning=false",
            ],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            creationflags=flags,
        )
        stderr_thread = threading.Thread(target=self.katago_log,
                                         name="KataGoStdErr")
        stdout_thread = threading.Thread(target=self.katago_output,
                                         name="KataGoStdOut")
        self.katago = process
        stderr_thread.start()
        stdout_thread.start()

    def katago_log(self) -> None:
        """Log for KataGo."""
        if self.katago is None:
            return
        pipe = self.katago.stderr
        assert pipe is not None
        for line in iter(pipe.readline, b""):
            self.log(f"[KataGo] {line.decode('utf-8').rstrip()}")
        pipe.close()

    def katago_output(self) -> None:
        """Process output for KataGo."""
        katago = self.katago
        if katago is None:
            return
        pipe = katago.stdout
        assert pipe is not None
        try:
            for line in iter(pipe.readline, b""):
                with self.analysis_cond:
                    self.analysis_results.append(json.loads(line))
                    self.analysis_cond.notify_all()
        except Exception as e:
            self.log(f"Error parsing output from KataGo: {e}")
            raise e
        finally:
            pipe.close()
            with self.analysis_cond:
                self.analysis_exit = True
                self.analysis_cond.notify_all()

    def katago_send_command(self, command: Any) -> None:
        """Send analysis command to KataGo."""
        katago = self.katago
        if katago is None:
            return
        with self.command_lock:
            pipe = katago.stdin
            assert pipe is not None
            if not pipe.closed:
                pipe.write(json.dumps(command).encode())
                pipe.write(b"\n")
                pipe.flush()

    def katago_wait_output(self) -> Any:
        """Wait for KataGo output."""
        katago = self.katago
        if katago is None:
            raise ValueError(_("KataGo is not running"))
        while True:
            with self.analysis_cond:
                while True:
                    if self.aborted:
                        raise RuntimeError(_("Aborted"))
                    ret = katago.poll()
                    if ret is not None:
                        raise RuntimeError(
                            _("Unexpected termination: Error %d") % ret)
                    if self.analysis_exit:
                        katago.kill()
                        time.sleep(0)
                        continue
                    if self.analysis_results:
                        break
                    self.analysis_cond.wait()
                obj = self.analysis_results.pop(0)
            if not isinstance(obj, dict):
                raise ValueError(_("Unknown response from KataGo"))
            if "error" in obj:
                raise RuntimeError(_("KataGo error: %s") % obj['error'])
            if "warning" in obj:
                self.log(_("KataGo warning: %s") % obj['warning'])
                continue
            return obj

    def katago_stop(self) -> None:
        """Stop KataGo gracefully."""
        katago = self.katago
        if katago is None:
            return
        if katago.returncode is not None:
            return
        self.katago_send_command({"id": "term", "action": "terminate_all"})
        with self.command_lock:
            assert katago.stdin is not None
            katago.stdin.close()

    def katago_terminate(self) -> None:
        """Terminate KataGo."""
        if self.katago is None:
            return
        try:
            self.katago_stop()
            self.katago.wait(10)
        except (subprocess.TimeoutExpired, OSError):
            self.katago.kill()
            self.katago.wait()
        self.katago = None

    def katago_exit(self) -> int:
        """Stop KataGo and exit process."""
        if self.katago is None:
            raise ValueError(_("KataGo is not running"))
        self.katago_stop()
        try:
            ret = self.katago.wait(10)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(_("Unable to stop KataGo process")) from e
        self.katago = None
        return ret

    def abort(self) -> None:
        """Abort analysis."""
        self.aborted = True
        self.katago_stop()
        with self.analysis_cond:
            self.analysis_cond.notify_all()

    def get_version(self) -> str:
        """Wait for KataGo to be ready."""
        self.katago_send_command({"id": "ver", "action": "query_version"})
        while True:
            obj = self.katago_wait_output()
            if obj["id"] == "ver":
                break
        return obj.get("version", "")

    def update_progress(self) -> None:
        """Update progress based on weight estimate."""
        total_weight = self.target_weight + self.weight
        cur_weight = self.cur_weight + self.weight_done
        self.progress(cur_weight / total_weight)

    def calc_komi(self) -> float:
        """Calculate real komi."""
        komi = self.calc_komi_iter(0)[0]
        komi_tries = {}
        self.weight -= self.min_weight
        while True:
            if komi in komi_tries:
                coeffs = polyfit(list(komi_tries.keys()),
                                 list(komi_tries.values()),
                                 degree=1)
                if abs(coeffs[0]) >= 0.001:
                    komi = round(-coeffs[1] / coeffs[0] * 2) / 2
                    if komi in komi_tries:
                        break
                komi = min(komi_tries,
                           key=lambda k: abs(komi_tries[k]))
                break
            self.log(_("Trying %s...") % format_float(komi, 1))
            diff, winrate, visits = self.calc_komi_iter(komi)
            komi_tries[komi] = winrate - 0.5
            self.log(_("Visits: %d; winrate: %s") %
                     (visits, format_float(winrate, 3)))
            if (komi + diff) in komi_tries:
                step = 0.5 if winrate > 0.5 else -0.5
                diff = 0
                while True:
                    diff += step
                    val = komi_tries.get(komi + diff, None)
                    if val is None:
                        break
                    if (winrate - 0.5) * val <= 0:
                        break
            if len(komi_tries) > 1:
                coeffs = polyfit(list(komi_tries.keys()),
                                 list(komi_tries.values()),
                                 degree=1)
                if abs(coeffs[0]) < 0.001:
                    komi += diff
                else:
                    new_komi = round(-coeffs[1] / coeffs[0] * 2) / 2
                    if abs(new_komi - komi) > 5 or new_komi in komi_tries:
                        komi += diff
                    else:
                        komi = new_komi
            else:
                komi += diff
                self.weight -= self.min_weight
        return komi

    def calc_komi_iter(self, init_komi: float) -> Tuple[float, float, float]:
        """Calculate metrics for komi."""
        target_visits = 1000000
        min_weight = self.min_weight / 5
        cur_visits = 0
        move_obj = {}
        self.target_weight = self.min_weight
        self.cur_weight = 0
        if self.game_moves:
            colour, move = self.game_moves[-1]
            custom_settings = {
                "moves": self.game_moves[:-1]
            }
        else:
            colour = "W" if self.colour == "B" else "B"
            move = "pass"
            custom_settings = {
                "moves": [],
                "initialPlayer": colour,
            }
        while self.cur_weight < self.target_weight:
            self.katago_send_command({
                "id": "komi",
                "initialStones": self.init_moves,
                "rules": "chinese",
                "komi": init_komi,
                "boardXSize": 19,
                "boardYSize": 19,
                "maxVisits": target_visits,
                "reportDuringSearchEvery": 1.0,
                **custom_settings,
                "allowMoves": [{
                    "player": colour,
                    "moves": [move],
                    "untilDepth": 1,
                }],
                "overrideSettings": {
                    "conservativePass": True,
                },
            })
            while True:
                obj = self.katago_wait_output()
                if obj.get("id") != "komi":
                    continue
                move_infos = obj.get("moveInfos", [])
                move_infos = [x for x in move_infos
                              if x["move"] == move]
                if not move_infos:
                    continue
                move_obj = move_infos[0]
                visits = move_obj["edgeVisits"]
                if visits < cur_visits:
                    self.update_progress()
                    continue
                cur_visits = visits
                self.cur_weight = move_obj["edgeWeight"]
                if self.cur_weight >= min_weight:
                    radius = abs(move_obj["utility"] - move_obj["utilityLcb"])
                    self.recalculate_target_weight(radius)
                if self.cur_weight >= self.target_weight \
                        and obj.get("isDuringSearch", False):
                    self.katago_send_command({
                        "id": "komi_term",
                        "action": "terminate",
                        "terminateId": "komi"
                    })
                self.update_progress()
                if not obj.get("isDuringSearch", False):
                    break
            target_visits *= 2
        lead = move_obj["scoreLead"]
        winrate = move_obj["winrate"]
        self.weight += self.target_weight
        self.weight_done += self.cur_weight
        self.target_weight = 0
        self.cur_weight = 0
        return round(lead * 2) / 2, winrate, cur_visits

    def analyze_move(self, move_idx: int, komi: float) -> \
            Tuple[float, float, float, str]:
        """Analyze move."""
        target_visits = 1000000
        min_weight = self.min_weight / 5
        cur_visits = 0
        move_obj = {}
        proc_id = f"move-{move_idx}"
        self.weight -= self.min_weight
        self.target_weight = self.min_weight
        self.cur_weight = 0
        while self.cur_weight < self.target_weight:
            self.katago_send_command({
                "id": proc_id,
                "initialStones": self.init_moves,
                "moves": self.game_moves,
                "rules": "chinese",
                "komi": komi,
                "boardXSize": 19,
                "boardYSize": 19,
                "maxVisits": target_visits,
                "reportDuringSearchEvery": 1.0,
                "allowMoves": [{
                    "player": self.colour,
                    "moves": [self.moves[move_idx]],
                    "untilDepth": 1,
                }],
            })
            while True:
                obj = self.katago_wait_output()
                if obj.get("id") != proc_id:
                    continue
                move_infos = obj.get("moveInfos", [])
                move_infos = [x for x in move_infos
                              if x["move"] == self.moves[move_idx]]
                if not move_infos:
                    continue
                move_obj = move_infos[0]
                visits = move_obj["edgeVisits"]
                if visits < cur_visits:
                    self.update_progress()
                    continue
                cur_visits = visits
                self.cur_weight = move_obj["edgeWeight"]
                if self.cur_weight >= min_weight:
                    radius = abs(move_obj["utility"] - move_obj["utilityLcb"])
                    self.recalculate_target_weight(radius)
                if self.cur_weight >= self.target_weight \
                        and obj.get("isDuringSearch", False):
                    self.katago_send_command({
                        "id": f"{proc_id}_term",
                        "action": "terminate",
                        "terminateId": proc_id,
                    })
                self.update_progress()
                if not obj.get("isDuringSearch", False):
                    break
            target_visits *= 2
        self.update_progress()
        res = move_obj["utility"]
        radius = abs(move_obj["utility"] - move_obj["utilityLcb"])
        if self.colour == "W":
            res = -res
        self.weight += self.target_weight
        self.weight_done += self.cur_weight
        self.target_weight = 0
        self.cur_weight = 0
        return res, radius, cur_visits, " ".join(move_obj["pv"])

    def recalculate_target_weight(self, radius: float) -> None:
        """Recalculate target weight for progress bar."""
        scale = radius / self.max_radius
        self.target_weight = max([
            self.cur_weight,
            self.cur_weight * scale * scale,
            self.min_weight
        ])


class Board(wx.Control):
    """Board class."""

    LABELS = "ABCDEFGHJKLMNOPQRST"
    HOSHI = [(3, 3), (3, 9), (3, 15), (9, 3), (9, 9),
             (9, 15), (15, 3), (15, 9), (15, 15)]

    def __init__(self, parent, board: sgf_board.Board, colour: str,
                 marks: List[Tuple[int, int]], *args, **kwargs) -> None:
        """Construct board."""
        kwargs["style"] = (kwargs.get("style", 0) | wx.BORDER_NONE |
                           wx.FULL_REPAINT_ON_RESIZE)
        super().__init__(parent, *args, **kwargs)
        self.board = board
        self.colour = colour
        self.sel_x = None
        self.sel_y = None
        self.marks = marks
        self.has_sel = True
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)

    def on_paint(self, _evt) -> None:
        """Paint event handler."""
        dc = wx.BufferedPaintDC(self)
        self.draw_board(dc)

    def on_mouse_move(self, evt: wx.MoveEvent) -> None:
        """Mouse move event handler."""
        if not self.has_sel:
            return
        (x, y) = evt.GetPosition()
        width, height = self.GetClientSize()
        if not width or not height:
            self.sel_x = None
            self.sel_y = None
            return
        board_size = min(width, height)
        pad_left = (width - board_size) // 2
        pad_top = (height - board_size) // 2
        space_size = board_size * 0.02
        row_size = (board_size - space_size * 3) / 20
        i_f = (x - pad_left - space_size * 2 - row_size) / row_size
        j_f = (y - pad_top - space_size) / row_size
        i = int(i_f + 1) - 1
        j = 19 - int(j_f + 1)
        if i >= 0 and j >= 0 \
                and i < 19 and j < 19 \
                and self.board.get(j, i) is None:
            new_x = i
            new_y = j
        else:
            new_x = None
            new_y = None
        if self.sel_x != new_x or self.sel_y != new_y:
            self.sel_x = new_x
            self.sel_y = new_y
            self.Refresh()

    def set_board(self, board: sgf_board.Board, colour: str,
                  marks: List[Tuple[int, int]],
                  preserve_sel: bool = False) -> None:
        """Set board."""
        self.board = board
        self.colour = colour
        if not preserve_sel:
            self.sel_x = None
            self.sel_y = None
        self.marks = marks
        self.Refresh()

    def draw_board(self, bdc: wx.BufferedPaintDC) -> None:
        """Draw board."""
        width, height = self.GetClientSize()
        if not width or not height:
            return
        board_size = min(width, height)
        pad_left = (width - board_size) // 2
        pad_top = (height - board_size) // 2
        space_size = board_size * 0.02
        board_edge = space_size * 0.25
        row_size = (board_size - space_size * 3) / 20
        stone_size = int(row_size * 0.48)
        mark_size = int(row_size * 0.25)

        dc = wx.GCDC(bdc)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        dc.SetPen(wx.BLACK_PEN)
        dc.SetBrush(wx.WHITE_BRUSH)
        dc.DrawRectangle(int(pad_left + space_size * 2 - board_edge +
                             row_size),
                         int(pad_top + space_size - board_edge),
                         int(row_size * 19 + board_edge * 2),
                         int(row_size * 19 + board_edge * 2))
        font_size = int(row_size * 0.75)
        if font_size > 0:
            dc.SetFont(wx.Font(wx.FontInfo(wx.Size(0, font_size))))
            dc.SetTextForeground(self.GetForegroundColour())
            dc.SetTextBackground(wx.TransparentColour)
            for i in range(19):
                text = Board.LABELS[i]
                cw, ch = dc.GetTextExtent(text)
                x = int(pad_left + row_size * (i + 1) +
                        (row_size - cw) / 2 + space_size * 2)
                y = int(pad_top + board_size - row_size - space_size)
                dc.DrawText(text, x, y)
            for i in range(19):
                text = str(19 - i)
                cw, ch = dc.GetTextExtent(text)
                x = int(pad_left + row_size - cw + space_size)
                y = int(pad_top + row_size * i +
                        (row_size - ch) / 2 + space_size)
                dc.DrawText(text, x, y)
        dc.SetPen(wx.BLACK_PEN)
        for i in range(19):
            x1 = int(pad_left + space_size * 2 + row_size * 1.5)
            y1 = int(pad_top + space_size + row_size * (i + 0.5))
            x2 = int(pad_left + space_size * 2 + row_size * 19.5)
            y2 = int(pad_top + space_size + row_size * (i + 0.5))
            if i in (0, 18):
                dc.SetPen(wx.Pen(wx.BLACK, 3))
            else:
                dc.SetPen(wx.Pen(wx.BLACK, 1))
            dc.DrawLine(x1, y1, x2, y2)
        for i in range(19):
            x1 = int(pad_left + space_size * 2 + row_size * (i + 1.5))
            y1 = int(pad_top + space_size + row_size * 0.5)
            x2 = int(pad_left + space_size * 2 + row_size * (i + 1.5))
            y2 = int(pad_top + space_size + row_size * 18.5)
            if i in (0, 18):
                dc.SetPen(wx.Pen(wx.BLACK, 3))
            else:
                dc.SetPen(wx.Pen(wx.BLACK, 1))
            dc.DrawLine(x1, y1, x2, y2)
        dc.SetPen(wx.BLACK_PEN)
        dc.SetBrush(wx.BLACK_BRUSH)
        for i, j in Board.HOSHI:
            x = int(pad_left + space_size * 2 + row_size * (i + 1.5))
            y = int(pad_top + space_size + row_size * (j + 0.5))
            dc.DrawCircle(x, y, 2)
        dc.SetPen(wx.Pen(wx.BLACK, 2))
        for j in range(19):
            for i in range(19):
                colour = self.board.get(j, i)
                if colour is not None:
                    if colour == "b":
                        dc.SetBrush(wx.BLACK_BRUSH)
                    else:
                        dc.SetBrush(wx.WHITE_BRUSH)
                    x = int(pad_left + space_size * 2 + row_size * (i + 1.5))
                    y = int(pad_top + space_size + row_size * (18 - j + 0.5))
                    dc.DrawCircle(x, y, stone_size)
        if self.has_sel and self.sel_x is not None and self.sel_y is not None:
            if self.colour == "b":
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 128)))
            else:
                dc.SetPen(wx.Pen(wx.Colour(0, 0, 0, 192), 1))
                dc.SetBrush(wx.Brush(wx.Colour(255, 255, 255, 192)))
            x = int(pad_left + space_size * 2 + row_size * (self.sel_x + 1.5))
            y = int(pad_top + space_size + row_size * (18 - self.sel_y + 0.5))
            dc.DrawCircle(x, y, stone_size)
        for i, j in self.marks:
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            colour = self.board.get(j, i)
            if colour is not None:
                if colour == "b":
                    dc.SetPen(wx.Pen(wx.WHITE, 3))
                else:
                    dc.SetPen(wx.Pen(wx.BLACK, 3))
            else:
                dc.SetPen(wx.Pen(wx.BLACK, 3))
            x = int(pad_left + space_size * 2 + row_size * (i + 1.5))
            y = int(pad_top + space_size + row_size * (18 - j + 0.5))
            dc.DrawCircle(x, y, mark_size)


class NumberCtrl(wx.TextCtrl):
    """Number control class."""

    def __init__(self, parent, id, value: Union[float, None],
                 *args,
                 precision: int = 0, allow_none: bool = False,
                 min_val: Union[float, None] = None,
                 max_val: Union[float, None] = None,
                 custom_fmt: Union[Callable[[float], float], None] = None,
                 **kwargs) -> None:
        """Construct number control."""
        super().__init__(parent, id, NumberCtrl.format_value(
            value=value,
            precision=precision,
            allow_none=allow_none,
            min_val=min_val,
            max_val=max_val,
            custom_fmt=custom_fmt,
        ), *args, **kwargs)
        self.precision = precision
        self.allow_none = allow_none
        self.min_val = min_val
        self.max_val = max_val
        self.custom_fmt = custom_fmt
        self.Bind(wx.EVT_KILL_FOCUS, self.handle_blur)

    def get_raw_value(self) -> Union[float, None]:
        """Get raw value."""
        try:
            return parse_float(self.Value, self.precision)
        except ValueError:
            return None

    def reformat_value(self) -> None:
        """Reformat current value."""
        self.Value = NumberCtrl.format_value(
            value=self.get_raw_value(),
            precision=self.precision,
            allow_none=self.allow_none,
            min_val=self.min_val,
            max_val=self.max_val,
            custom_fmt=self.custom_fmt,
        )

    def get_number_value(self) -> Union[None, float]:
        """Get number value."""
        self.reformat_value()
        return self.get_raw_value()

    def handle_blur(self, event: wx.Event) -> None:
        """Handle blur event."""
        self.reformat_value()
        event.Skip()

    @staticmethod
    def format_value(value: Union[float, None], precision: int,
                     allow_none: bool, min_val: Union[float, None],
                     max_val: Union[float, None],
                     custom_fmt: Union[Callable[[float], float], None]) -> str:
        """Format value."""
        if value is None:
            if not allow_none:
                value = min_val if min_val is not None else 0
            else:
                return ""
        if min_val is not None:
            value = max(value, min_val)
        if max_val is not None:
            value = min(value, max_val)
        if custom_fmt is not None:
            value = custom_fmt(value)
        return format_float(value, precision)


class MainFrame(wx.Frame):
    """Main frame class."""

    def __init__(self) -> None:
        """Construct main frame."""
        super().__init__(None, wx.ID_ANY,
                         title=_("SGF Analyzer"),
                         style=wx.DEFAULT_FRAME_STYLE | wx.TAB_TRAVERSAL)
        self.filename = None
        self.init_board = sgf_board.Board(19)
        self.moves = []
        self.move_idx = 0
        self.sel_move_idx = 0
        self.first_to_move = "b"
        self.sel_moves = []
        self.analyzer = None
        self.analysis_start = None
        self.config: wx.ConfigBase = wx.Config.Get()  # type: ignore

        if IS_FROZEN and IS_WINDOWS:
            self.SetIcon(wx.Icon(sys.executable, wx.BITMAP_TYPE_ICO))
        elif IS_FROZEN and IS_MAC:
            pass
        else:
            icon_bundle = wx.IconBundle()
            icon_img = wx.Image(os.path.join(DATA_DIR, "icon.png"),
                                wx.BITMAP_TYPE_PNG)
            icon_big = wx.Icon()
            icon_big.CopyFromBitmap(wx.Bitmap(icon_img))
            for size in [16, 32, 48, 64, 96, 128, 256]:
                icon = wx.Icon()
                icon.CopyFromBitmap(wx.Bitmap(icon_img.Scale(size, size)))
                icon_bundle.AddIcon(icon)
            icon_bundle.AddIcon(icon_big)
            self.SetIcons(icon_bundle)

        self.main_panel = wx.Panel(self)

        self.SetBackgroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE))
        self.SetForegroundColour(
            wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT))

        content_sizer = wx.BoxSizer(wx.VERTICAL)

        content_sizer.Add(self.FromDIP(wx.Size(0, 5)), 0, wx.EXPAND, 0)

        self.title_label = wx.StaticText(self.main_panel, wx.ID_ANY, "")
        self.title_label.SetFont(self.GetFont().Scaled(1.5))
        content_sizer.Add(self.title_label, 0,
                          wx.ALL | wx.EXPAND, self.FromDIP(10))

        content_sizer.Add(wx.StaticLine(self.main_panel, wx.ID_ANY), 0,
                          wx.ALL | wx.EXPAND, self.FromDIP(5))
        content_sizer.Add(self.FromDIP(wx.Size(0, 5)), 0, wx.EXPAND, 0)
        self.pages = [
            self.create_page_0(),
            self.create_page_1(),
            self.create_page_2(),
            self.create_page_3(),
            self.create_page_4(),
            self.create_page_5(),
        ]
        self.titles = [
            _("Select SGF file"),
            _("Select position"),
            _("Select moves"),
            _("Analysis settings"),
            _("Confirm settings"),
            _("Analyzing..."),
        ]
        self.page_loaders = [
            self.load_page_1,
            self.load_page_2,
            self.load_page_3,
            self.load_page_4,
            self.load_page_5,
        ]
        self.current_page = self.pages[0]
        self.current_page_idx = 0
        for page in self.pages:
            page.Hide()
            content_sizer.Add(page, 1, wx.EXPAND, 0)
        content_sizer.Add(self.FromDIP(wx.Size(0, 5)), 0, wx.EXPAND, 0)

        content_sizer.Add(wx.StaticLine(self.main_panel, wx.ID_ANY), 0,
                          wx.ALL | wx.EXPAND, self.FromDIP(5))

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer.Add(button_row, 0,
                          wx.ALIGN_RIGHT | wx.ALL, self.FromDIP(5))

        self.back_btn = wx.Button(self.main_panel, wx.ID_ANY, _("< &Back"))
        button_row.Add(self.back_btn, 0, wx.ALL | wx.EXPAND, self.FromDIP(5))

        self.next_btn = wx.Button(self.main_panel, wx.ID_ANY, _("&Next >"))
        self.next_btn.SetDefault()
        button_row.Add(self.next_btn, 0, wx.ALL | wx.EXPAND, self.FromDIP(5))

        self.cancel_btn = wx.Button(self.main_panel, wx.ID_CANCEL,
                                    _("&Cancel"))
        button_row.Add(self.cancel_btn, 0, wx.ALL | wx.EXPAND, self.FromDIP(5))

        self.Bind(wx.EVT_BUTTON, self.on_back_click, self.back_btn)
        self.Bind(wx.EVT_BUTTON, self.on_next_click, self.next_btn)
        self.Bind(wx.EVT_BUTTON, self.on_cancel_click, self.cancel_btn)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.main_panel.SetSizer(content_sizer)
        self.SetSize(self.FromDIP(wx.Size(800, 800)))
        self.update_page()
        self.Center()

    def create_page_0(self) -> wx.Panel:
        """Create page 0 panel."""
        panel = wx.Panel(self.main_panel, wx.ID_ANY)
        panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_sizer.Add(content_sizer, 1,
                        wx.ALIGN_CENTER_VERTICAL | wx.ALL, self.FromDIP(30))

        sgf_sel_label = wx.StaticText(
            panel, wx.ID_ANY, _("Select SGF file to analyze"))
        content_sizer.Add(sgf_sel_label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))

        self.sgf_selector = wx.FilePickerCtrl(
            panel, wx.ID_ANY, "",
            message=_("Select SGF file"),
            wildcard=_("SGF Files (*.sgf)|*.sgf|All files|*.*"),
            style=wx.FLP_USE_TEXTCTRL | wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST)
        content_sizer.Add(self.sgf_selector, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        panel.SetSizer(panel_sizer)
        return panel

    def create_page_1(self) -> wx.Panel:
        """Create page 1 panel."""
        panel = wx.Panel(self.main_panel, wx.ID_ANY)
        board, colour, marks = self.calc_board()
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(panel, wx.ID_ANY,
                              _("Select position to analyze"))
        panel_sizer.Add(label, 0,
                        wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(10))
        self.board = Board(panel, board, colour, marks, wx.ID_ANY)
        self.board.has_sel = False
        panel_sizer.Add(self.board, 1,
                        wx.EXPAND | wx.ALL, self.FromDIP(5))
        button_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_beg = wx.Button(panel, wx.ID_ANY, "|<")
        button_row_sizer.Add(btn_beg, 0, 0, 0)
        btn_prev_fast = wx.Button(panel, wx.ID_ANY, "<<")
        button_row_sizer.Add(btn_prev_fast, 0, 0, 0)
        btn_prev = wx.Button(panel, wx.ID_ANY, "<")
        button_row_sizer.Add(btn_prev, 0, 0, 0)
        self.board_move_label = wx.StaticText(panel, wx.ID_ANY, "")
        button_row_sizer.Add(self.board_move_label, 0,
                             wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
                             self.FromDIP(5))
        btn_next = wx.Button(panel, wx.ID_ANY, ">")
        button_row_sizer.Add(btn_next, 0, 0, 0)
        btn_next_fast = wx.Button(panel, wx.ID_ANY, ">>")
        button_row_sizer.Add(btn_next_fast, 0, 0, 0)
        btn_end = wx.Button(panel, wx.ID_ANY, ">|")
        button_row_sizer.Add(btn_end, 0, 0, 0)
        panel_sizer.Add(button_row_sizer, 0,
                        wx.ALIGN_CENTER_HORIZONTAL | wx.LEFT | wx.RIGHT,
                        self.FromDIP(10))
        self.Bind(wx.EVT_BUTTON, self.on_board_beg, btn_beg)
        self.Bind(wx.EVT_BUTTON, self.on_board_prev_fast, btn_prev_fast)
        self.Bind(wx.EVT_BUTTON, self.on_board_prev, btn_prev)
        self.Bind(wx.EVT_BUTTON, self.on_board_next, btn_next)
        self.Bind(wx.EVT_BUTTON, self.on_board_next_fast, btn_next_fast)
        self.Bind(wx.EVT_BUTTON, self.on_board_end, btn_end)
        panel.SetSizer(panel_sizer)
        return panel

    def create_page_2(self) -> wx.Panel:
        """Create page 2 panel."""
        panel = wx.Panel(self.main_panel, wx.ID_ANY)
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(panel, wx.ID_ANY,
                              _("Select moves to compare"))
        panel_sizer.Add(label, 0,
                        wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(10))
        self.sel_board = Board(panel, self.board.board, self.board.colour,
                               self.sel_moves, wx.ID_ANY)
        panel_sizer.Add(self.sel_board, 1,
                        wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP,
                        self.FromDIP(5))
        panel.SetSizer(panel_sizer)
        self.sel_board.Bind(wx.EVT_LEFT_UP, self.on_sel_click)
        return panel

    def create_page_3(self) -> wx.Panel:
        """Create page 3 panel."""
        katago_path = self.config.Read("EnginePath")
        config_path = self.config.Read("ConfigPath")
        model_path = self.config.Read("ModelPath")
        guess_config = (not config_path and
                        not self.config.HasEntry("ConfigPath"))

        if not katago_path or not config_path or not model_path:
            katrain_conf_path = os.path.join(
                wx.GetUserHome(), ".katrain", "config.json")
            if os.path.exists(katrain_conf_path):
                with open(katrain_conf_path, "rt", encoding="utf-8") as f:
                    katrain_conf = json.load(f)
                engine_conf = katrain_conf.get("engine", {})
                if not katago_path:
                    katago_path = engine_conf.get("katago", "")
                    if not os.path.exists(katago_path):
                        katago_path = ""
                if guess_config:
                    config_path = engine_conf.get("config", "")
                    if not os.path.exists(config_path):
                        config_path = ""
                    else:
                        guess_config = False
                if not model_path:
                    model_path = engine_conf.get("model", "")
                    if not os.path.exists(model_path):
                        model_path = ""
            katrain_mac = "/Applications/KaTrain.app/Contents"
            if IS_MAC and os.path.exists(katrain_mac):
                if not katago_path:
                    katago_path = os.path.join(
                        katrain_mac,
                        "Frameworks/katrain/KataGo/katago-osx"
                    )
                    if not os.path.exists(katago_path):
                        katago_path = ""
                if guess_config:
                    config_path = os.path.join(
                        katrain_mac,
                        "Resources/katrain/KataGo/analysis_config.cfg"
                    )
                    if not os.path.exists(config_path):
                        config_path = ""
                if not model_path:
                    models_dir_mac = os.path.join(
                        katrain_mac,
                        "Resources/katrain/models"
                    )
                    models_mac = [os.path.join(models_dir_mac, x)
                                  for x in os.listdir(models_dir_mac)
                                  if x.endswith(".bin.gz")]
                    if models_mac:
                        model_path = models_mac[0]

        panel = wx.ScrolledWindow(self.main_panel, wx.ID_ANY,
                                  style=wx.TAB_TRAVERSAL)
        panel.SetScrollRate(0, self.FromDIP(10))
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_sizer.Add(content_sizer, 1,
                        wx.EXPAND | wx.ALL, self.FromDIP(30))
        label = wx.StaticText(panel, wx.ID_ANY, _("Select KataGo executable"))
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(5))
        if IS_WINDOWS:
            exe_wildcard = _("Executable (*.exe)|*.exe|All files|*.*")
        else:
            exe_wildcard = _("All files|*.*")
        self.kata_selector = wx.FilePickerCtrl(
            panel, wx.ID_ANY, "",
            message=_("Select KataGo executable"),
            wildcard=exe_wildcard,
            style=wx.FLP_USE_TEXTCTRL | wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST)
        self.kata_selector.Path = katago_path
        content_sizer.Add(self.kata_selector, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        label = wx.StaticText(
            panel, wx.ID_ANY,
            _("Select KataGo configuration (leave blank for default settings)")
        )
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        self.config_selector = wx.FilePickerCtrl(
            panel, wx.ID_ANY, "",
            message=_("Select KataGo configuration file"),
            wildcard=_("KataGo configuration (*.cfg)|*.cfg|All files|*.*"),
            style=wx.FLP_USE_TEXTCTRL | wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST)
        self.config_selector.Path = config_path
        content_sizer.Add(self.config_selector, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        label = wx.StaticText(panel, wx.ID_ANY, _("Select KataGo model"))
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        self.model_selector = wx.FilePickerCtrl(
            panel, wx.ID_ANY, "",
            message=_("Select KataGo model"),
            wildcard=_("KataGo model (*.bin.gz;*.bin)|*.bin.gz;*.bin|"
                       "All files|*.*"),
            style=wx.FLP_USE_TEXTCTRL | wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST)
        self.model_selector.Path = model_path
        content_sizer.Add(self.model_selector, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        content_sizer.Add(self.FromDIP(wx.Size(0, 30)), 0, wx.EXPAND, 0)
        label = wx.StaticText(panel, wx.ID_ANY, _("Minimum weight"))
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        self.min_weight_ctrl = NumberCtrl(panel, wx.ID_ANY, value=50000,
                                          precision=2, allow_none=False,
                                          min_val=0, max_val=None)
        content_sizer.Add(self.min_weight_ctrl, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        label = wx.StaticText(panel, wx.ID_ANY, _("Maximum radius"))
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        self.max_radius_ctrl = NumberCtrl(panel, wx.ID_ANY, value=0.5,
                                          precision=3, allow_none=False,
                                          min_val=0, max_val=None)
        content_sizer.Add(self.max_radius_ctrl, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        label = wx.StaticText(
            panel, wx.ID_ANY,
            _("Assumed komi (leave blank to calculate automatically; "
              "recommended)"))
        content_sizer.Add(label, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        self.komi_ctrl = NumberCtrl(panel, wx.ID_ANY, value=None,
                                    precision=1, allow_none=True,
                                    min_val=-150, max_val=150,
                                    custom_fmt=lambda x: round(x * 2) / 2)
        content_sizer.Add(self.komi_ctrl, 0,
                          wx.EXPAND | wx.ALL, self.FromDIP(5))
        panel.SetSizer(panel_sizer)
        return panel  # type: ignore

    def create_page_4(self) -> wx.Panel:
        """Create page 4 panel."""
        panel = wx.Panel(self.main_panel, wx.ID_ANY)
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        self.confirm_textarea = wx.TextCtrl(
            panel, wx.ID_ANY, "",
            style=(wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL |
                   wx.TE_DONTWRAP | wx.BORDER_SIMPLE)
        )
        panel_sizer.Add(self.confirm_textarea, 1,
                        wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(10))
        panel.SetSizer(panel_sizer)
        return panel

    def create_page_5(self) -> wx.Panel:
        """Create page 5 panel."""
        panel = wx.Panel(self.main_panel, wx.ID_ANY)
        panel_sizer = wx.BoxSizer(wx.VERTICAL)

        self.progress_bar = wx.Gauge(
            panel, wx.ID_ANY,
            style=wx.GA_HORIZONTAL | wx.GA_SMOOTH | wx.GA_PROGRESS
        )
        panel_sizer.Add(self.progress_bar, 0,
                        wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                        self.FromDIP(10))
        self.progress_label = wx.StaticText(panel, wx.ID_ANY, "")
        panel_sizer.Add(self.progress_label, 0,
                        wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                        self.FromDIP(10))

        self.log_textarea = wx.TextCtrl(
            panel, wx.ID_ANY, "",
            style=(wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL |
                   wx.TE_DONTWRAP | wx.BORDER_SIMPLE)
        )
        panel_sizer.Add(self.log_textarea, 1,
                        wx.EXPAND | wx.LEFT | wx.RIGHT, self.FromDIP(10))
        panel.SetSizer(panel_sizer)
        return panel

    def load_page_1(self) -> bool:
        """Load page 1."""
        filename = self.sgf_selector.Path
        if not filename:
            return False
        if filename == self.filename:
            return True
        try:
            with open(filename, "rt", encoding="utf-8") as f:
                game = sgf.Sgf_game.from_string(f.read())

            self.init_board, self.moves = sgf_moves.get_setup_and_moves(game)
            root_node = game.get_root()
            if root_node.has_property("PL"):
                self.first_to_move = root_node.get("PL")
            else:
                self.first_to_move = "b"
            self.move_idx = 0
            self.update_board()
            self.filename = filename
            self.sel_move_idx = 0
            self.sel_moves = []
        except (OSError, ValueError):
            wx.MessageBox(_("Failed to load SGF file"), _("Error"),
                          wx.ICON_ERROR, self)
            return False
        return True

    def load_page_2(self) -> bool:
        """Load page 2."""
        if self.sel_move_idx != self.move_idx:
            self.sel_moves = []
        self.sel_move_idx = self.move_idx
        self.update_sel_board()
        return True

    def load_page_3(self) -> bool:
        """Load page 3."""
        if len(self.sel_moves) < 2:
            return False
        return True

    def load_page_4(self) -> bool:
        """Load page 4."""
        katago_path = self.kata_selector.Path
        config_path = self.config_selector.Path
        model_path = self.model_selector.Path
        if not config_path:
            config_path = os.path.join(DATA_DIR, "config.cfg")
        if not katago_path or not config_path or not model_path \
                or not os.path.exists(katago_path) \
                or not os.path.exists(config_path) \
                or not os.path.exists(model_path) \
                or not os.access(katago_path, os.X_OK):
            return False
        min_weight = self.min_weight_ctrl.get_number_value()
        max_radius = self.max_radius_ctrl.get_number_value()
        komi = self.komi_ctrl.get_number_value()
        if not min_weight or not max_radius:
            return False
        moves_str = ""
        for i, j in self.sel_moves:
            moves_str += f"\t{Board.LABELS[i]}{j + 1}\n"
        min_weight_str = format_float(min_weight, 2)
        max_radius_str = format_float(max_radius, 3)
        komi_str = (format_float(komi, 1) if komi is not None
                    else _("Automatic komi"))
        self.confirm_textarea.Value = _(
            "SGF file\n\t%s\n\n"
            "Position\n\tmove %d\n\n"
            "Moves to compare\n%s\n\n"
            "KataGo path\n\t%s\n\n"
            "KataGo config\n\t%s\n\n"
            "Model path\n\t%s\n\n\n"
            "Minimum weight\n\t%s\n\n"
            "Maximum radius\n\t%s\n\n"
            "Komi\n\t%s"
        ) % (self.filename, self.move_idx, moves_str, katago_path, config_path,
             model_path, min_weight_str, max_radius_str, komi_str)
        return True

    def load_page_5(self) -> bool:
        """Load page 5."""
        katago_path = self.kata_selector.Path
        config_path = self.config_selector.Path
        model_path = self.model_selector.Path
        self.config.Write("EnginePath", katago_path)
        self.config.Write("ConfigPath", config_path)
        self.config.Write("ModelPath", model_path)
        self.config.Flush()
        if not config_path:
            config_path = os.path.join(DATA_DIR, "config.cfg")
        init_moves = []
        for j in range(19):
            for i in range(19):
                move = self.init_board.get(j, i)
                if move is not None:
                    init_moves.append((move.upper(),
                                       f"{Board.LABELS[i]}{j + 1}"))
        game_moves = []
        for col, move in self.moves[:self.move_idx]:
            if move is None:
                game_moves.append((col.upper(), "pass"))
            else:
                j, i = move
                game_moves.append((col.upper(),
                                   f"{Board.LABELS[i]}{j + 1}"))
        moves = []
        for i, j in self.sel_moves:
            moves.append(f"{Board.LABELS[i]}{j + 1}")
        min_weight = self.min_weight_ctrl.get_number_value()
        max_radius = self.max_radius_ctrl.get_number_value()
        komi = self.komi_ctrl.get_number_value()
        assert min_weight is not None
        assert max_radius is not None
        self.analyzer = Analyzer(
            log=lambda msg: wx.CallAfter(self.analyzer_log, msg),
            progress=lambda progress: wx.CallAfter(
                self.update_progress, progress),
            finish=lambda: wx.CallAfter(self.finish_analysis),
            katago_path=katago_path,
            config_path=config_path,
            model_path=model_path,
            init_moves=init_moves,
            game_moves=game_moves,
            move_colour=self.sel_board.colour.upper(),
            moves=moves,
            min_weight=min_weight,
            max_radius=max_radius / 100,
            komi=komi,
        )
        return True

    def analyzer_log(self, msg: str) -> None:
        """Log message from analyzer."""
        self.log_textarea.AppendText(msg + "\n")

    def finish_analysis(self) -> None:
        """Finish analysis."""
        if self.analyzer is None:
            return
        self.analyzer.thread.join()
        aborted = self.analyzer.aborted
        self.cancel_btn.Disable()
        self.next_btn.Enable()
        self.analyzer = None
        self.title_label.SetLabelText(_("Analysis complete"))
        if not aborted:
            wx.Bell()

    def update_progress(self, progress: float) -> None:
        """Update analysis progress."""
        if self.analysis_start is None:
            self.analysis_start = time.time()
        else:
            elapsed = time.time() - self.analysis_start
            total = elapsed / progress
            elapsed_str = wx.TimeSpan.Milliseconds(
                int(elapsed * 1000)).Format("%H:%M:%S")
            total_str = wx.TimeSpan.Milliseconds(
                int(total * 1000)).Format("%H:%M:%S")
            self.progress_label.SetLabelText(
                _("Estimated time %s / %s") % (elapsed_str, total_str))

        self.progress_bar.Value = int(progress * 100 + 0.5)

    def update_page(self) -> None:
        """Update page."""
        self.current_page.Hide()
        self.current_page = self.pages[self.current_page_idx]
        self.current_page.Show()
        if self.current_page_idx == 5:
            self.back_btn.Disable()
            self.next_btn.Disable()
        else:
            self.back_btn.Enable(self.current_page_idx != 0)
        if self.current_page_idx == 4:
            self.next_btn.SetLabel(_("&Start"))
        elif self.current_page_idx == len(self.pages) - 1:
            self.next_btn.SetLabel(_("&Finish"))
        else:
            self.next_btn.SetLabel(_("&Next >"))
        self.title_label.SetLabelText(self.titles[self.current_page_idx])
        self.update_layout()
        if self.current_page_idx < 4:
            self.current_page.SetFocus()

    def update_layout(self) -> None:
        """Update window layout."""
        self.SetMinClientSize(self.main_panel.GetSizer().GetMinSize())
        min_size = self.GetEffectiveMinSize()
        cur_size = self.GetSize()
        cur_size.IncTo(min_size)
        self.SetSize(cur_size)
        self.current_page.Layout()
        self.main_panel.Layout()

    def on_back_click(self, _evt) -> None:
        """Select previous page."""
        if self.current_page_idx == 0:
            return
        self.current_page_idx -= 1
        self.update_page()

    def on_next_click(self, _evt) -> None:
        """Select next page."""
        if self.current_page_idx == len(self.pages) - 1:
            self.Close()
            return
        if not self.page_loaders[self.current_page_idx]():
            return
        self.current_page_idx += 1
        self.update_page()

    def on_cancel_click(self, _evt) -> None:
        """Handle cancel button."""
        if wx.MessageBox(_("Are you sure you want to cancel?"), _("Cancel"),
                         wx.YES_NO | wx.ICON_INFORMATION, self) != wx.YES:
            return
        if self.analyzer is not None:
            self.cancel_btn.Disable()
            self.analyzer.abort()
            return
        self.Close()

    def on_board_beg(self, _evt) -> None:
        """Move to the beginning."""
        self.move_idx = 0
        self.update_board()

    def on_board_end(self, _evt) -> None:
        """Move to the end."""
        self.move_idx = len(self.moves)
        self.update_board()

    def on_board_prev(self, _evt) -> None:
        """Move back."""
        if self.move_idx == 0:
            return
        self.move_idx -= 1
        self.update_board()

    def on_board_next_fast(self, _evt) -> None:
        """Move forward fast."""
        if self.move_idx + 5 >= len(self.moves):
            self.move_idx = len(self.moves)
        else:
            self.move_idx += 5
        self.update_board()

    def on_board_prev_fast(self, _evt) -> None:
        """Move back fast."""
        if self.move_idx < 5:
            self.move_idx = 0
        else:
            self.move_idx -= 5
        self.update_board()

    def on_board_next(self, _evt) -> None:
        """Move forward."""
        if self.move_idx == len(self.moves):
            return
        self.move_idx += 1
        self.update_board()

    def on_sel_click(self, _evt) -> None:
        """Handle move selection click."""
        sel_x = self.sel_board.sel_x
        sel_y = self.sel_board.sel_y
        if sel_x is None or sel_y is None:
            return
        for i, (x, y) in enumerate(self.sel_moves):
            if x == sel_x and y == sel_y:
                self.sel_moves.pop(i)
                break
        else:
            self.sel_moves.append((sel_x, sel_y))
        self.update_sel_board()

    def on_close(self, event: wx.CloseEvent) -> None:
        """Handle window close."""
        if self.analyzer is None:
            event.Skip()
        elif event.CanVeto():
            event.Veto()
        else:
            event.Skip()

    def calc_board(self) -> Tuple[sgf_board.Board, str, List[Tuple[int, int]]]:
        """Calculate board."""
        if self.move_idx > 0:
            colour, move = self.moves[self.move_idx - 1]
            if move is None:
                marks = []
            else:
                marks = [(move[1], move[0])]
            next_colour = "w" if colour == "b" else "b"
        else:
            next_colour = self.first_to_move
            marks = []
        board = self.init_board.copy()
        for colour, move in self.moves[:self.move_idx]:
            if move is None:
                continue
            row, col = move
            board.play(row, col, colour)
        return board, next_colour, marks

    def update_board(self) -> None:
        """Update board."""
        board, colour, marks = self.calc_board()
        self.board.set_board(board, colour, marks)
        self.board_move_label.SetLabelText(_("Move %d") % (self.move_idx))
        self.update_layout()

    def update_sel_board(self) -> None:
        """Update selection board."""
        self.sel_board.set_board(self.board.board,
                                 self.board.colour,
                                 self.sel_moves,
                                 preserve_sel=True)


class App(wx.App):
    """App class."""

    # pylint: disable=invalid-name,attribute-defined-outside-init

    def OnInit(self) -> bool:
        """Init handler."""
        wx.StandardPaths.Get().SetFileLayout(wx.StandardPaths.FileLayout_XDG)
        self.locale = wx.Locale(wx.LANGUAGE_DEFAULT)
        self.locale.AddCatalogLookupPathPrefix(
            os.path.join(ROOT_DIR, "locale"))
        self.locale.AddCatalog("KatagoFairCompare")
        locale.setlocale(locale.LC_ALL, "")
        self.SetAppName("KatagoFairCompare")
        main_frame = MainFrame()
        self.SetTopWindow(main_frame)
        main_frame.Show()
        return True


if __name__ == "__main__":
    app = App()
    app.MainLoop()
