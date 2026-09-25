import sys
from argparse import ArgumentParser
from bulbs.zengge import Zengge
from bulbs.zengge_9byte import Zengge9Byte
from bulbs.zengge_23byte import Zengge23Byte

VERSION_MAPPING = {
    "AK001-ZJ2101": Zengge9Byte,
    "AK001-ZJ2145": Zengge9Byte,
    "AK001-ZJ21411" : Zengge23Byte
}

def parse_segment_colors(raw):
    entries = raw.split(";")
    expected = Zengge23Byte.SEGMENT_COUNT
    if len(entries) != expected:
        raise ValueError(f"exactly {expected} segment colors are required")

    colors = []
    for entry in entries:
        components = entry.split(",")
        if len(components) != 3:
            raise ValueError("each segment color must be R,G,B")
        try:
            color = tuple(int(component.strip()) for component in components)
        except ValueError as error:
            raise ValueError("segment RGB values must be integers") from error
        if any(component < 0 or component > 255 for component in color):
            raise ValueError("segment RGB values must be between 0 and 255")
        colors.append(color)
    return colors

def parse_counter(raw):
    try:
        counter = int(raw, 0)
    except ValueError as error:
        raise ValueError("counter must be an integer from 0 to 255") from error
    if not 0 <= counter <= 255:
        raise ValueError("counter must be from 0 to 255")
    return counter

def process_rgb_or_error(parser, bulb, rgb, brightness=None):
    try:
        if isinstance(bulb, Zengge23Byte):
            return bulb.process_rgb(rgb, brightness=brightness)
        if brightness is not None:
            parser.error("-brightness is only supported for AK001-ZJ21411")
        return bulb.process_rgb(rgb)
    except ValueError as error:
        parser.error(str(error))

def process_white_or_error(bulb, white):
    try:
        return bulb.process_white(white)
    except NotImplementedError as error:
        bulb.print_error(str(error))

def get_zengge(ip):
    bulb = Zengge(ip)
    version = bulb.get_version()
    BulbClass = VERSION_MAPPING.get(version, Zengge)
    return BulbClass(ip)

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("-ip", help="provide the IP for the lightbulb; i.e. -ip 192.168.2.2")
    parser.add_argument("-raw", help="accept colon separated raw hex string; i.e. -raw 71:23:0f")
    parser.add_argument("-rgb", help="accept comma separated rgb values; i.e. -rgb 100,155,75")
    parser.add_argument("-segments", help="set 20 segment colors as semicolon-separated R,G,B triplets")
    parser.add_argument("-brightness", type=int, help="override AK001-ZJ21411 brightness (0-100 percent) for -rgb/-segments")
    parser.add_argument("-counter", type=parse_counter, help="set initial AK001-ZJ21411 frame counter (0-255, accepts values like 0x1D); default 0 is unverified")
    parser.add_argument("-white", help="accept value of white temp and brightness (0-255); i.e. -white 150, 255")
    parser.add_argument("-warm", help="accept value of warm white (0-255); i.e. -warm 150")
    parser.add_argument("-cool", help="accept value of cool white (0-255); i.e. -cool 150")
    parser.add_argument("-power", help="accept 'on' or 'off'; i.e. -power on")
    parser.add_argument("-status", help="get the bulb's status", action='store_true')
    parser.add_argument("-version", help="get the bulb's version", action='store_true')
    parsed_args = parser.parse_args()
    
    bulb = get_zengge(parsed_args.ip)

    if parsed_args.ip is None:
        bulb.print_error(None, 'Must provide IP.')

    if parsed_args.counter is not None:
        if not isinstance(bulb, Zengge23Byte):
            parser.error("-counter is only supported for AK001-ZJ21411")
        if not (parsed_args.rgb or parsed_args.segments) or parsed_args.raw:
            parser.error("-counter requires -rgb or -segments, not -raw")
        bulb.counter = parsed_args.counter

    if parsed_args.brightness is not None:
        if not (parsed_args.rgb or parsed_args.segments):
            parser.error("-brightness requires -rgb or -segments")
        if not 0 <= parsed_args.brightness <= 100:
            parser.error("-brightness must be between 0 and 100")
    
    if parsed_args.version:
        bulb.print_version()
        sys.exit()
    
    if parsed_args.status:
        status = bulb.get_status()
        sys.exit()
    
    values = None
    
    if parsed_args.raw:
        values = bulb.process_raw(parsed_args.raw)
    elif parsed_args.segments:
        if not isinstance(bulb, Zengge23Byte):
            bulb.print_error("-segments is only supported for AK001-ZJ21411")
        try:
            colors = parse_segment_colors(parsed_args.segments)
            values = bulb.process_segments(colors, brightness=parsed_args.brightness)
        except ValueError as error:
            parser.error(str(error))
    elif parsed_args.rgb:
        values = process_rgb_or_error(
            parser, bulb, parsed_args.rgb, brightness=parsed_args.brightness
        )
    elif parsed_args.white:
        white = parsed_args.white.split(',')
        values = process_white_or_error(bulb, white)
    elif parsed_args.warm:
        values = process_white_or_error(bulb, [0, parsed_args.warm])
    elif parsed_args.cool:
        values = process_white_or_error(bulb, [255, parsed_args.cool])
    elif parsed_args.power:
        values = bulb.process_power(parsed_args.power)
    
    if values:
        bulb.send(values)
    else:
        bulb.print_version()
        bulb.get_status()
