"""Upload the knowledge file and the reply corpus to ERPNext as private files for the Thunderbird add-on.

The add-on (``thunderbird-addon/``) reads ``reply-knowledge.md`` and ``reply-corpus.json`` from
the private file folder ``Home/Antworten`` of ERPNext with the user's API key, so nothing from
the private mytools repository has to be copied to the team's laptops. Run this after every
change of the knowledge file or a new corpus; an existing file of the same name is replaced.

Usage:
    python3 reply_material_upload.py --server URL --key KEY --secret SECRET [--knowledge FILE] [--corpus FILE]
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import reply_corpus
import reply_knowledge
from api import Api
from frappeclient import FrappeClient

FOLDER = 'Home/Antworten'


def ensure_folder() -> None:
    rows = Api.api.get_list('File', filters={'is_folder': 1, 'folder': 'Home', 'file_name': FOLDER.split('/')[-1]},
                            fields=['name'], limit_page_length=1)
    if not rows:
        Api.api.insert({'doctype': 'File', 'is_folder': 1, 'file_name': FOLDER.split('/')[-1], 'folder': 'Home'})


def upload(path: str) -> dict[str, Any]:
    """Replace the private file of that name in the folder; returns the new File row."""
    file_name = os.path.basename(path)
    for old in Api.api.get_list('File', filters={'file_name': file_name, 'folder': FOLDER, 'is_private': 1},
                                fields=['name'], limit_page_length=10):
        Api.api.delete('File', old['name'])
    with open(path, 'rb') as f:
        response = Api.api.session.post(Api.api.url + '/api/method/upload_file', headers=Api.api.headers,
                                        data={'is_private': 1, 'folder': FOLDER, 'file_name': file_name},
                                        files={'file': (file_name, f)})
    response.raise_for_status()
    return response.json()['message']


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--server', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--secret', required=True)
    parser.add_argument('--knowledge', default=reply_knowledge.DEFAULT_OUT)
    parser.add_argument('--corpus', default=reply_corpus.DEFAULT_PATH)
    args = parser.parse_args(argv)
    Api.api = FrappeClient(args.server, api_key=args.key, api_secret=args.secret)
    ensure_folder()
    for path in (args.knowledge, args.corpus):
        if not os.path.exists(path):
            print('fehlt, nicht hochgeladen:', path)
            continue
        row = upload(path)
        print('hochgeladen: {} -> {} ({} Bytes)'.format(path, row.get('file_url'), row.get('file_size')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
