#!/usr/bin/env python3
"""
Reproduce las tramas CAN crudas de un archivo .mf4 (bus logging) en una
interfaz SocketCAN (por ejemplo vcan0), respetando los tiempos originales.

Dependencias:
    pip install asammdf python-can numpy

Preparar la interfaz virtual (Linux):
    sudo modprobe vcan
    sudo ip link add dev vcan0 type vcan
    sudo ip link set up vcan0

Uso:
    python3 mf4_can_replay.py viaje.mf4 --channel vcan0
    python3 mf4_can_replay.py viaje.mf4 --channel vcan0 --loop --speed 1.0
    python3 mf4_can_replay.py viaje.mf4 --info        # solo resumen del archivo
"""
import argparse
import sys
import time

import numpy as np
from asammdf import MDF
import can


def _get(mdf, name, group):
    """Devuelve la señal 'name' del grupo, o None si no existe."""
    try:
        return mdf.get(name, group=group)
    except Exception:
        return None


def load_frames(path, bus_channel=None):
    """Extrae (timestamps, ids, extended, datos) de todos los grupos CAN_DataFrame."""
    mdf = MDF(path)
    locations = mdf.whereis("CAN_DataFrame.ID")
    if not locations:
        sys.exit("No se encontró 'CAN_DataFrame.ID'. ¿El .mf4 contiene bus logging CAN crudo?")

    groups = sorted({g for g, _ in locations})
    all_ts, all_ids, all_ext, all_data = [], [], [], []
    skipped_fd = 0

    for g in groups:
        sig_id = _get(mdf, "CAN_DataFrame.ID", g)
        sig_data = _get(mdf, "CAN_DataFrame.DataBytes", g)
        if sig_id is None or sig_data is None or len(sig_id.samples) == 0:
            continue

        ts = np.asarray(sig_id.timestamps, dtype=np.float64)
        raw_ids = np.asarray(sig_id.samples).astype(np.uint32)
        data = np.asarray(sig_data.samples)
        n = len(ts)

        # Longitud real de los datos
        sig_len = _get(mdf, "CAN_DataFrame.DataLength", g) or _get(mdf, "CAN_DataFrame.DLC", g)
        lengths = (np.asarray(sig_len.samples).astype(int) if sig_len is not None
                   else np.full(n, data.shape[1] if data.ndim > 1 else 8))

        # Extended ID
        sig_ide = _get(mdf, "CAN_DataFrame.IDE", g)
        ext = (np.asarray(sig_ide.samples).astype(bool) if sig_ide is not None
               else (raw_ids & 0x1FFFFFFF) > 0x7FF)

        # CAN FD (se omiten: la reproducción es solo CAN clásico)
        sig_edl = _get(mdf, "CAN_DataFrame.EDL", g)
        is_fd = (np.asarray(sig_edl.samples).astype(bool) if sig_edl is not None
                 else np.zeros(n, dtype=bool))

        # Canal físico del bus (1, 2, ...)
        sig_bus = _get(mdf, "CAN_DataFrame.BusChannel", g)
        bus = (np.asarray(sig_bus.samples).astype(int) if sig_bus is not None
               else np.zeros(n, dtype=int))

        for i in range(n):
            if bus_channel is not None and bus[i] != bus_channel:
                continue
            if is_fd[i] or lengths[i] > 8:
                skipped_fd += 1
                continue
            all_ts.append(ts[i])
            all_ids.append(int(raw_ids[i] & 0x1FFFFFFF))
            all_ext.append(bool(ext[i]))
            all_data.append(bytes(int(b) for b in data[i][: lengths[i]]))

    if not all_ts:
        sys.exit("No se extrajo ninguna trama (revisa --bus-channel).")
    if skipped_fd:
        print(f"Aviso: se omitieron {skipped_fd} tramas CAN FD / de más de 8 bytes.")

    order = np.argsort(all_ts, kind="stable")
    ts = np.asarray(all_ts)[order]
    ids = [all_ids[i] for i in order]
    ext = [all_ext[i] for i in order]
    data = [all_data[i] for i in order]
    return ts - ts[0], ids, ext, data


def replay(bus, ts, ids, ext, data, speed, start_at=0.0, max_gap=None):
    first = int(np.searchsorted(ts, start_at))
    if first >= len(ts):
        sys.exit(f"--start {start_at} s supera la duración del log ({ts[-1]:.1f} s).")
    t0 = ts[first]
    start = time.monotonic()
    last_report = start
    sent = 0
    skipped = 0.0          # tiempo de huecos que se comprime (--max-gap)
    prev = ts[first]
    for i in range(first, len(ts)):
        gap = ts[i] - prev
        prev = ts[i]
        if gap > 2.0:
            extra = ""
            if max_gap is not None and gap > max_gap:
                skipped += gap - max_gap
                extra = f" (comprimido a {max_gap:.1f} s)"
            print(f"  Hueco en la grabación: {gap:.1f} s sin tramas "
                  f"(desde t = {ts[i] - gap:.1f} s){extra}")
        delay = start + (ts[i] - t0 - skipped) / speed - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        bus.send(can.Message(arbitration_id=ids[i], is_extended_id=ext[i],
                             data=data[i], is_fd=False))
        sent += 1
        now = time.monotonic()
        if now - last_report >= 5.0:
            print(f"  t = {ts[i]:7.1f} / {ts[-1]:.1f} s   tramas enviadas: {sent}")
            last_report = now


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", help="Archivo .mf4 con tramas CAN crudas")
    p.add_argument("--channel", default="vcan0", help="Interfaz SocketCAN de destino")
    p.add_argument("--bus-channel", type=int, help="Filtrar por canal de bus del log (1, 2, ...)")
    p.add_argument("--speed", type=float, default=1.0, help="Factor de velocidad de reproducción")
    p.add_argument("--start", type=float, default=0.0,
                   help="Empezar la reproducción en este segundo del log")
    p.add_argument("--max-gap", type=float,
                   help="Comprimir huecos de la grabación mayores a estos segundos")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--info", action="store_true", help="Solo mostrar resumen y salir")
    args = p.parse_args()

    ts, ids, ext, data = load_frames(args.file, args.bus_channel)
    unique_ids = sorted(set(ids))
    print(f"{len(ts)} tramas, {ts[-1]:.1f} s de duración, {len(unique_ids)} IDs distintos")

    if args.info:
        print(f"{'ID':>8s} {'tramas':>8s} {'primera (s)':>12s} {'frecuencia':>12s}")
        for uid in unique_ids:
            t_id = ts[[k for k, v in enumerate(ids) if v == uid]]
            span = t_id[-1] - t_id[0]
            freq = f"{(len(t_id) - 1) / span:.2f} Hz" if span > 0 else "-"
            print(f"0x{uid:>6X} {len(t_id):>8d} {t_id[0]:>12.1f} {freq:>12s}")
        gaps = np.diff(ts)
        print("\nHuecos más largos entre tramas consecutivas (cualquier ID):")
        for k in np.argsort(gaps)[::-1][:5]:
            print(f"  {gaps[k]:8.1f} s sin tramas, desde t = {ts[k]:.1f} s")
        return

    with can.interface.Bus(channel=args.channel, interface="socketcan") as bus:
        print(f"Reproduciendo en {args.channel} (Ctrl+C para detener)")
        try:
            while True:
                replay(bus, ts, ids, ext, data, args.speed, args.start, args.max_gap)
                if not args.loop:
                    break
                print("Reiniciando reproducción...")
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()