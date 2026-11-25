from .app import main

if __name__ == "__main__":  # the backtest worker process imports this module too, and must not open a window
    raise SystemExit(main())
