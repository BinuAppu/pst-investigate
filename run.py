from pst_investigator.app import create_app
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PST Investigator")
    parser.add_argument("--source", default=None, help="PST directory")
    parser.add_argument("--data", default="./data", help="Application data directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    app = create_app(args.data, args.source)
    app.run(host=args.host, port=args.port, debug=False)
