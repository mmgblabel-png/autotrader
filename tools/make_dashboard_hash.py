#!/usr/bin/env python3
from getpass import getpass
from autotrader.api.auth import make_password_hash

password = getpass("Dashboard password (12+ characters): ")
print(make_password_hash(password))
