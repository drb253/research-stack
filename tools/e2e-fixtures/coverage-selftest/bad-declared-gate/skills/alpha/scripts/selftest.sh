expect_exit 0 "gate passes" python3 scripts/gate.py --clean
expect_exit 1 "gate fails" python3 scripts/gate.py --broken
