"""Local entry point for the PayPro Campaign Automaton.

Examples:
    python main.py serve
    python main.py init
    python main.py run --campaign wegmetdiekilos-bronze --force
"""
from campaign_automaton.cli import main

if __name__ == "__main__":
    main()
