#!/usr/bin/env python3
"""
Nodo ROS 2: lee tramas de una interfaz SocketCAN, decodifica una señal con un
archivo DBC y la publica como std_msgs/Float32.

Dependencias:
    pip install cantools python-can
    ROS 2 instalado y "sourced"

Uso:
    # 1) Buscar señales o mensajes por nombre en el DBC
    python3 can_speed_node.py --dbc vehiculo.dbc --search speed

    # 2) Publicar (--frame-id si el nombre de la señal se repite en varios mensajes)
    python3 can_speed_node.py --dbc vehiculo.dbc --signal Speed --frame-id 0x7 \
        --channel vcan0 --topic vehicle/speed_kmh --scale 3.6

    # --scale 3.6 si la señal está en m/s y quieres km/h
"""
import argparse
import sys

import can
import cantools

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32


def search_signals(db, pattern):
    pattern = pattern.lower()
    found = False
    for m in db.messages:
        for s in m.signals:
            if pattern in s.name.lower() or pattern in m.name.lower():
                found = True
                print(f"Señal: {s.name:30s} Mensaje: {m.name:25s} "
                      f"ID: 0x{m.frame_id:X} ({m.frame_id})  Unidad: {s.unit or '-'}  "
                      f"Escala: {s.scale}  Offset: {s.offset}")
    if not found:
        print(f"No hay señales ni mensajes que contengan '{pattern}' en el DBC.")


def find_signal(db, name, frame_id=None):
    """Devuelve la lista de (mensaje, señal) que coinciden con el nombre."""
    matches = []
    for m in db.messages:
        if frame_id is not None and m.frame_id != frame_id:
            continue
        for s in m.signals:
            if s.name == name:
                matches.append((m, s))
    return matches


class SpeedPublisher(Node):
    def __init__(self, topic):
        super().__init__("can_speed_node")
        self.pub = self.create_publisher(Float32, topic, 10)

    def publish(self, value):
        msg = Float32()
        msg.data = float(value)
        self.pub.publish(msg)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dbc", required=True, help="Archivo DBC")
    p.add_argument("--search", help="Buscar señales por nombre y salir")
    p.add_argument("--signal", help="Nombre exacto de la señal de velocidad")
    p.add_argument("--frame-id", type=lambda x: int(x, 0),
                   help="ID del mensaje (decimal o 0x..), si el nombre de la señal se repite")
    p.add_argument("--channel", default="vcan0", help="Interfaz SocketCAN (vcan0, can0...)")
    p.add_argument("--topic", default="vehicle/speed_kmh")
    p.add_argument("--scale", type=float, default=1.0, help="Factor de conversión de unidades")
    args = p.parse_args()

    db = cantools.database.load_file(args.dbc, strict=False)  # tolera señales solapadas

    if args.search:
        search_signals(db, args.search)
        return
    if not args.signal:
        sys.exit("Indica --signal o usa --search para encontrarla.")

    matches = find_signal(db, args.signal, args.frame_id)
    if not matches:
        sys.exit(f"La señal '{args.signal}' no existe en el DBC (o no en ese --frame-id). "
                 f"Usa --search.")
    if len(matches) > 1:
        opciones = ", ".join(f"{m.name} (0x{m.frame_id:X})" for m, _ in matches)
        sys.exit(f"La señal '{args.signal}' aparece en varios mensajes: {opciones}. "
                 f"Elige uno con --frame-id.")
    msg_def, sig_def = matches[0]

    rclpy.init()
    node = SpeedPublisher(args.topic)
    node.get_logger().info(
        f"Escuchando {args.channel}: {msg_def.name} (0x{msg_def.frame_id:X}) -> "
        f"{args.signal} [{sig_def.unit or 'sin unidad'}] -> '{args.topic}'")

    bus = can.interface.Bus(channel=args.channel, interface="socketcan")
    try:
        while rclpy.ok():
            frame = bus.recv(timeout=0.1)
            if frame is None:
                continue
            if (frame.arbitration_id != msg_def.frame_id
                    or frame.is_extended_id != msg_def.is_extended_frame):
                continue
            try:
                decoded = msg_def.decode(bytes(frame.data), decode_choices=False)
            except Exception as e:
                node.get_logger().warn(f"No se pudo decodificar la trama: {e}")
                continue
            if args.signal in decoded:
                node.publish(decoded[args.signal] * args.scale)
    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()