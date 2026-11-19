"""Check a campaign's pickup history before switching its static layout."""

from pathlib import Path
import queue
import sys
import threading


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path[:0] = [str(TOOLS), str(ROOT), str(TOOLS / "vendor")]

from pbzmod.profile_switch import cli, open_session, switch


SOURCE_LABELS = {
    "map_pickup": "地图光点", "chest": "宝箱", "boss": "Boss",
    "quest": "任务", "enemy_drop": "战斗结算",
}


def mode_label(enabled):
    return "启用随机" if enabled else "关闭随机"


def region_for(point, row):
    place = row.get("place")
    if place:
        return row.get("region") or place.partition(" · ")[0]
    prefix, separator, _ = point.partition(".")
    return row.get("region") or row.get("world") or (prefix if separator else SOURCE_LABELS.get(row["source"], "其他"))


def item_label(row):
    if row.get("itemLabel"):
        return row["itemLabel"]
    parts = (row.get("label") or "").split(" | ", 2)
    if len(parts) > 1 and parts[1]:
        return parts[1]
    return row.get("itemName") or row["item"]


def show_window(name):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    window = tk.Tk()
    window.withdraw()
    window.title("影之刃零 · 切换战役模式")
    if not name:
        messagebox.showinfo(window.title(), "请在 PBZRandomizer.exe 中选定战役，再打开切换窗口。", parent=window)
        window.destroy()
        return 1
    try:
        session = open_session(ROOT, name)
    except (KeyError, OSError, ValueError) as error:
        messagebox.showerror(window.title(), str(error), parent=window)
        window.destroy()
        return 1

    previous = set(session.current.granted)
    selected = set()
    available = set()
    failed = set()
    data = session.points
    origins = session.current.origins
    all_regions = "全部地区"
    regions = sorted({region_for(point, row) for point, row in data.items()})
    target = not session.enabled
    query = tk.StringVar()
    region = tk.StringVar(value=all_regions)
    complete = tk.BooleanVar(value=False)
    status = tk.StringVar()
    imported = tk.StringVar(value=("原版档首次启用：点击状态可依次选择已领、仍可领、保留原位。不能确定或已错过的点保留原位。"
                                   if session.initial_vanilla else "核对本轮进度后，勾选已领取的点位。"))
    details = tk.StringVar(value="选中一行查看完整点位信息。")
    result_queue = queue.Queue()
    busy = False

    window.geometry("1020x680")
    window.minsize(770, 540)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    panel = ttk.Frame(window, padding=18)
    panel.grid(sticky="nsew")
    panel.columnconfigure(0, weight=1)
    panel.rowconfigure(4, weight=1)

    ttk.Label(panel, text=session.campaign.name, font=("Microsoft YaHei UI", 17, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(panel, text=f"当前布局 · 随机{'开启' if session.enabled else '关闭'}").grid(row=1, column=0, sticky="w", pady=(3, 8))
    ttk.Label(panel, text="请先退出游戏。此后使用本战役的同一个游戏槽位。已经确认的点位会保留。", wraplength=720).grid(
        row=2, column=0, sticky="w", pady=(0, 9),
    )

    filters = ttk.Frame(panel)
    filters.grid(row=3, column=0, sticky="ew", pady=(0, 6))
    filters.columnconfigure(3, weight=1)
    ttk.Label(filters, text="地区").grid(row=0, column=0, sticky="w")
    ttk.Combobox(filters, values=[all_regions, *regions], textvariable=region, state="readonly", width=20).grid(
        row=0, column=1, padx=(6, 14), sticky="w",
    )
    ttk.Label(filters, text="搜索点位或物品").grid(row=0, column=2, sticky="w")
    ttk.Entry(filters, textvariable=query).grid(row=0, column=3, padx=(6, 0), sticky="ew")

    table_frame = ttk.Frame(panel)
    table_frame.grid(row=4, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)
    table = ttk.Treeview(table_frame, show="headings", columns=("checked", "region", "point", "original", "current"))
    table.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    table.configure(yscrollcommand=scroll.set)
    for name_, title, width, stretch in (
        ("checked", "点位状态", 92, False), ("region", "地区", 116, False), ("point", "点位", 342, True),
        ("original", "原奖励", 148, True), ("current", "本轮奖励", 148, True),
    ):
        table.heading(name_, text=title)
        table.column(name_, width=width, minwidth=70, stretch=stretch)
    table.tag_configure("historical", foreground="#6d6b65")

    ttk.Label(panel, textvariable=details, wraplength=720).grid(row=5, column=0, sticky="w", pady=(8, 0))
    ttk.Label(panel, textvariable=imported, wraplength=720).grid(row=6, column=0, sticky="w", pady=(6, 0))
    ttk.Label(panel, textvariable=status).grid(row=7, column=0, sticky="w", pady=(6, 0))

    buttons = ttk.Frame(panel)
    buttons.grid(row=8, column=0, sticky="ew", pady=(9, 0))
    buttons.columnconfigure(2, weight=1)

    def count_selected():
        status.set(f"此前已确认 {len(previous)} 处 · 本轮已勾选 {len(selected)} 处")
        if session.initial_vanilla:
            status.set(f"已领 {len(selected)} 处 · 仍可领 {len(available)} 处 · 保留原位 {len(data) - len(selected) - len(available)} 处")

    def label_for(point):
        if point in previous:
            return "已确认"
        if point in selected:
            return "✓ 已领"
        if point in failed:
            return "任务已失败"
        if point in available:
            return "仍可领"
        if session.initial_vanilla or point in session.protected:
            return "保留原位"
        return "□"

    def refresh(*_):
        table.delete(*table.get_children())
        details.set("选中一行查看完整点位信息。")
        term = query.get().strip().casefold()
        wanted = region.get()
        for point, row in sorted(data.items()):
            area = region_for(point, row)
            if wanted != all_regions and wanted != area:
                continue
            reward = data[origins[point]]
            label = row.get("label") or point
            original_label, current_label = item_label(row), item_label(reward)
            if term and term not in " ".join((point, label, original_label, current_label, row["item"], reward["item"])).casefold():
                continue
            nearby = (row.get("place") or "").partition(" · ")[2] or point
            table.insert("", "end", iid=point, values=(label_for(point), area, nearby, original_label, current_label),
                         tags=("historical",) if point in previous else ())

    def toggle(point):
        if busy or not point or point in previous or point in failed:
            return
        if point in selected:
            selected.remove(point)
            if session.initial_vanilla:
                available.add(point)
        elif point in available:
            available.remove(point)
        else:
            selected.add(point)
        table.set(point, "checked", label_for(point))
        complete.set(False)
        count_selected()

    def on_click(event):
        if table.identify_region(event.x, event.y) == "cell" and table.identify_column(event.x) == "#1":
            point = table.identify_row(event.y)
            table.focus_set()
            table.focus(point)
            table.selection_set(point)
            toggle(point)
            return "break"

    def on_double_click(event):
        if table.identify_region(event.x, event.y) == "cell" and table.identify_column(event.x) != "#1":
            toggle(table.identify_row(event.y))

    def show_details(_event):
        point = table.focus()
        if point in data:
            row = data[point]
            description = row.get("label") or point
            details.set(f"{description}\n本轮奖励 {item_label(data[origins[point]])}")

    def from_json():
        file = filedialog.askopenfilename(parent=window, title="选择已导出的当前槽位 JSON",
                                          filetypes=(("存档 JSON", "*.json"),))
        if not file:
            return
        try:
            summary = session.import_receipts(file)
        except (KeyError, OSError, ValueError) as error:
            messagebox.showerror(window.title(), str(error), parent=window)
            return
        taken = set(summary.claimed)
        selected.update(taken - previous)
        if session.initial_vanilla:
            failed.clear()
            failed.update(summary.failed)
            selected.difference_update(failed)
            available.clear()
            available.update(p for p in summary.unclaimed if data[p]["source"] in {"map_pickup", "chest"} and p not in selected)
        complete.set(False)
        imported.set(f"JSON 确认 {len(taken)} 处已领，{len(summary.unknown)} 处缺少记录。请核对槽位及已错过的任务。")
        refresh()
        count_selected()

    def change_controls(*_):
        switch_button.configure(state="normal" if complete.get() and not busy else "disabled")

    def finish():
        nonlocal busy
        try:
            success, details = result_queue.get_nowait()
        except queue.Empty:
            window.after(140, finish)
            return
        busy = False
        if success:
            messagebox.showinfo(window.title(), f"已{mode_label(target)}。返回启动器，使用同一游戏槽位继续战役。", parent=window)
            window.destroy()
            return
        import_button.configure(state="normal")
        complete.set(False)
        count_selected()
        messagebox.showerror(window.title(), details, parent=window)

    def start():
        nonlocal busy
        if busy or not complete.get():
            return
        busy = True
        change_controls()
        import_button.configure(state="disabled")
        status.set("正在构建并核对新布局…")
        claimed = previous | selected

        def work():
            try:
                switch(session, enabled=target, claimed=claimed, confirm_complete=True,
                       available=available if session.initial_vanilla else None)
            except Exception as error:
                result_queue.put((False, str(error)))
            else:
                result_queue.put((True, ""))

        threading.Thread(target=work).start()
        window.after(140, finish)

    import_button = ttk.Button(buttons, text="从槽位 JSON 填入…", command=from_json)
    import_button.grid(row=0, column=0, padx=(0, 9))
    ttk.Checkbutton(buttons, text="我已核对完整领取清单，当前槽位没有回退", variable=complete).grid(row=0, column=1, sticky="w")
    switch_button = ttk.Button(buttons, text=mode_label(target), command=start, state="disabled")
    switch_button.grid(row=0, column=3, sticky="e")
    if session.initial_vanilla:
        def mark_accessible():
            if busy:
                return
            candidates = {p for p in table.get_children() if data[p]["source"] in {"map_pickup", "chest"}} - selected - failed
            if candidates and messagebox.askyesno(window.title(), f"确认筛选结果中尚未勾选的 {len(candidates)} 个光点和宝箱均未领取，且仍可到达？", parent=window):
                available.update(candidates)
                complete.set(False)
                refresh()
                count_selected()
        ttk.Button(filters, text="这些光点与宝箱均仍可领…", command=mark_accessible).grid(row=0, column=4, padx=(8, 0))
    table.bind("<Button-1>", on_click)
    table.bind("<Double-Button-1>", on_double_click)
    table.bind("<<TreeviewSelect>>", show_details)
    table.bind("<space>", lambda _event: toggle(table.focus()))
    query.trace_add("write", refresh)
    region.trace_add("write", refresh)
    complete.trace_add("write", change_controls)
    window.protocol("WM_DELETE_WINDOW", lambda: None if busy else window.destroy())
    refresh()
    count_selected()
    window.deiconify()
    window.mainloop()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and (len(args) != 1 or args[0].startswith("-")):
        sys.exit(cli(ROOT, args))
    sys.exit(show_window(args[0] if args else ""))
