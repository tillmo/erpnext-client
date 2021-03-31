#!/bin/bash

# Debian and Ubuntu installer for erpnext client

# .deb dependencies
sudo apt install -y git poppler-utils python3-pip python3-tk

# get sources
git clone https://github.com/tillmo/erpnext-client.git

# settings
DIR=$(pwd)/erpnext-client
mkdir -p $HOME/.config/PySimpleGUI/settings
SETTINGS=$HOME/.config/PySimpleGUI/settings/erpnext.json
echo -n '{"-folder-": "' >$SETTINGS
echo -n $DIR >>$SETTINGS
echo '"}' >>$SETTINGS

# create a launcher icon
cd $DIR
wget https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/Erpnext_logo.svg/240px-Erpnext_logo.svg.png -O erpnext.png

DESKTOP=$HOME/.local/share/applications/erpnext.desktop
echo "[Desktop Entry]" >$DESKTOP
echo "Encoding=UTF-8" >>$DESKTOP
echo "Name=erpnext-client" >>$DESKTOP
echo "Path=$DIR/" >>$DESKTOP
echo "Exec=$DIR/erpnext" >>$DESKTOP
echo "Type=Application" >>$DESKTOP
echo "Terminal=false" >>$DESKTOP
echo "Icon=$DIR/erpnext.png" >>$DESKTOP

# Python packages
cd $DIR
pip3 install -r requirements.txt




