# Reproducción y visualización de datos CAN

Este proyecto permite reproducir tramas CAN guardadas en un archivo MDF4
(`.mf4`), decodificar señales con un archivo DBC y publicar valores en ROS 2.
Incluye además un dashboard web de velocidad.

## Herramienta principal: `mf4_can_replay.py`

[`mf4_can_replay.py`](./mf4_can_replay.py) extrae las tramas CAN crudas de un
archivo `.mf4` y las envía a una interfaz SocketCAN conservando los tiempos de
la grabación. Por defecto utiliza `vcan0`, una interfaz CAN virtual. También
permite inspeccionar el contenido de la grabación sin transmitir tramas.

### Requisitos

- Linux con soporte SocketCAN y las herramientas `ip` (paquete `iproute2`).
- Python 3.
- Dependencias de Python:

  ```bash
  python3 -m pip install asammdf python-can numpy
  ```

### Crear una interfaz CAN virtual

Ejecuta una vez por sistema, o cuando necesites volver a crear la interfaz:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Si `vcan0` ya existe, no vuelvas a ejecutar `ip link add`; puedes comprobar su
estado con `ip link show vcan0`.

### Inspeccionar un archivo

El archivo de ejemplo incluido es `KIA.MF4`. Para mostrar la cantidad de
tramas, duración, IDs, frecuencia aproximada por ID y los cinco huecos más
largos entre tramas:

```bash
python3 mf4_can_replay.py KIA.MF4 --info
```

El resumen se calcula sobre las tramas clásicas extraídas. La opción `--info`
no transmite datos a la interfaz CAN.

### Reproducir tramas

Reproducción a velocidad original:

```bash
python3 mf4_can_replay.py KIA.MF4 --channel vcan0
```

Ejemplos con opciones:

```bash
# Reproducir a doble velocidad
python3 mf4_can_replay.py KIA.MF4 --channel vcan0 --speed 2.0

# Empezar en el segundo 30 de la grabación
python3 mf4_can_replay.py KIA.MF4 --channel vcan0 --start 30

# Repetir la grabación continuamente
python3 mf4_can_replay.py KIA.MF4 --channel vcan0 --loop

# Filtrar por el canal de bus registrado dentro del archivo MDF4
python3 mf4_can_replay.py KIA.MF4 --channel vcan0 --bus-channel 1

# Comprimir pausas largas a un máximo de 1 segundo
python3 mf4_can_replay.py KIA.MF4 --channel vcan0 --max-gap 1
```

`--channel` indica la interfaz SocketCAN de destino; `--bus-channel` filtra por
el canal de bus identificado dentro de la grabación `.mf4`. `--speed` es un
factor: `2.0` reproduce al doble de velocidad y `0.5` a la mitad. `--start` y
`--max-gap` se expresan en segundos. Se puede detener la reproducción con
`Ctrl+C`.

La herramienta reproduce CAN clásico. Las tramas CAN FD o con más de 8 bytes
se omiten y se informa de cuántas fueron descartadas. Si el archivo contiene
varios canales de bus, sin `--bus-channel` se consideran todos.

> **Precaución:** SocketCAN puede apuntar a una interfaz física, por ejemplo
> `can0`. Transmitir en ella envía tramas al bus conectado. Para pruebas,
> utiliza `vcan0` o un banco aislado y verifica el destino antes de reproducir.

## Flujo opcional: publicar velocidad en ROS 2

[`can_speed_node.py`](./can_speed_node.py) escucha una interfaz SocketCAN,
decodifica una señal según el DBC indicado y la publica como
`std_msgs/Float32`. Se puede conectar al flujo anterior para publicar una
señal reproducida:

1. Instala `cantools` y `python-can` en el entorno Python compatible con ROS 2:

   ```bash
   python3 -m pip install cantools python-can
   ```

2. En una terminal, inicia la reproducción:

   ```bash
   python3 mf4_can_replay.py KIA.MF4 --channel vcan0
   ```

3. En otra terminal, con ROS 2 configurado y cargado (`source` de la instalación
   y del workspace, si aplica), busca la señal en el DBC:

   ```bash
   python3 can_speed_node.py --dbc ev6_gps.dbc --search VehicleSpeed
   ```

4. Elige el ID que muestre la búsqueda y arranca el publicador. Por ejemplo,
   `VehicleSpeed` está definido en el mensaje `Temperature` con ID decimal
   `1979` (`0x7BB`) en el DBC incluido:

   ```bash
   python3 can_speed_node.py \
     --dbc ev6_gps.dbc \
     --signal VehicleSpeed \
     --frame-id 1979 \
     --channel vcan0 \
     --topic /vehicle/speed_kmh
   ```

El DBC declara `VehicleSpeed` en km/h, por lo que en este ejemplo no se necesita
conversión adicional. Para otras señales, `--scale` permite aplicar un factor
de conversión. Consulta todas las opciones con:

```bash
python3 can_speed_node.py --help
```

### Dashboard web

[`Dashboard/velocimetro_ros2.html`](./Dashboard/velocimetro_ros2.html) muestra
la velocidad publicada en ROS 2. Para conectarlo, inicia rosbridge en un
entorno con el paquete `rosbridge_server`:

```bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

Abre el HTML en un navegador. De forma predeterminada se conecta al WebSocket
`ws://<host-del-navegador>:9090` y escucha el tópico
`/vehicle/speed_kmh`. Si necesitas otro host o tópico, la página permite
configurarlos en la URL; también dispone de un modo de demostración con
`?demo=1`.

## Contenido de la carpeta

| Archivo o carpeta | Descripción |
| --- | --- |
| [`mf4_can_replay.py`](./mf4_can_replay.py) | Reproduce y analiza tramas CAN de archivos MDF4; herramienta principal. |
| [`KIA.MF4`](./KIA.MF4) | Archivo de datos MDF4 de ejemplo. |
| [`can_speed_node.py`](./can_speed_node.py) | Nodo ROS 2 para decodificar y publicar una señal CAN como `Float32`. |
| [`ev6_gps.dbc`](./ev6_gps.dbc) | Definiciones de mensajes y señales CAN para decodificación. |
| [`Dashboard/`](./Dashboard) | Recursos de la interfaz web del velocímetro. |
| [`KIAcan_msg/`](./KIAcan_msg) | Documentación PDF relacionada con CAN. |
| [`KIAcan_msg.zip`](./KIAcan_msg.zip) | Archivo ZIP con material relacionado con CAN. |
