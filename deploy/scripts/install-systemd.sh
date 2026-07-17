#!/usr/bin/env sh
set -eu

sudo install -d -m 0755 /etc/tripweave
sudo install -m 0644 deploy/systemd/tripweave.service /etc/systemd/system/tripweave.service
sudo systemctl daemon-reload
sudo systemctl enable tripweave.service
echo "Install /etc/tripweave/tripweave.env with mode 0600 before starting tripweave.service."
