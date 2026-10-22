"""Fake listener on 127.0.0.1:5432: records every inbound connection (who dialed
PostgreSQL) then closes it."""

import socket
import sys
import time

log = open(sys.argv[1], "a", buffering=1)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 5432))
s.listen(64)
while True:
    c, a = s.accept()
    log.write(f"{time.time():.3f} CONNECT from {a}\n")
    c.close()
