import rotulador
import re
import argparse


def ip(arg_value):
    REGEX_IP = re.compile("^((25[0-5]|(2[0-4]|1\\d|[1-9]|)\\d)\\.?\\b){4}$")
    if not REGEX_IP.match(arg_value):
        raise argparse.ArgumentTypeError(f"Invalid IP '{arg_value}'")
    return arg_value


def port(arg_value):
    if int(arg_value) > 65535 or int(arg_value) < 0:
        raise argparse.ArgumentTypeError(f"Invalid port '{arg_value}'")
    return int(arg_value)


parser = argparse.ArgumentParser(
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,
)
parser.add_argument(
    "-H",
    "--host",
    type=ip,
    required=False,
    default="0.0.0.0",
    help="host for the server to listen.",
)
parser.add_argument(
    "-P",
    "--port",
    type=port,
    required=False,
    default=5005,
    help="port for the server to listen.",
)
parser.add_argument(
    "-D", "--debug", action="store_true", help="Start server in debug mode"
)
args = parser.parse_args()

rotulador.app.run(host=args.host, port=args.port, debug=args.debug)
