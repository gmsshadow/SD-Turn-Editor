## SD Turn Editor (Order GUI)

Cross-platform desktop GUI (Windows/Linux) to import Stellar Dominion turn reports and generate validated YAML order files.

### Status

Work in progress. Current milestone: import turn report text files and store them under `data/Turns/<turnNumber>/`.

### Run (dev)

1. Install Python 3.11+
2. Install dependencies:

```bash
python -m pip install -e .
```

3. Start the GUI:

```bash
python -m sd_order_gui
```

