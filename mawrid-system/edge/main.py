"""Durable local JSONL collector; emits no sensor values and creates no sessions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

SYSTEM=Path(__file__).resolve().parents[1]
if not __package__: sys.path.insert(0,str(SYSTEM))
from edge.core import Outbox, InputError, ClaimLost, canonical_uuid, ingest_file, ingest_stream
from edge.sender import LocalTransport, flush_once, watch


def emit(value):
    print(json.dumps(value,ensure_ascii=False,allow_nan=False),flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=SYSTEM/'edge/var/outbox.sqlite3')
    commands=parser.add_subparsers(dest='command',required=True)
    ingest=commands.add_parser('ingest',help='Validate JSONL and durably enqueue without network calls')
    ingest.add_argument('--input',required=True,help='JSONL file or - for stdin; input is never modified')
    ingest.add_argument('--session-id',required=True)
    ingest.add_argument('--input-kind',choices=('measured','fixture'),required=True)
    flush=commands.add_parser('flush',help='Send only the pinned session FIFO to the loopback API')
    flush.add_argument('--session-id',required=True);flush.add_argument('--port',type=int,default=8787)
    modes=flush.add_mutually_exclusive_group(required=True)
    modes.add_argument('--once',action='store_true');modes.add_argument('--watch',action='store_true')
    status=commands.add_parser('status');status.add_argument('--session-id')
    args=parser.parse_args(argv)
    box=None
    try:
        if getattr(args,'session_id',None): canonical_uuid(args.session_id,'session_id')
        box=Outbox(args.database)
        if args.command=='status': emit(box.status(args.session_id));exit_code=0
        elif args.command=='ingest':
            result=(ingest_stream(box,sys.stdin.buffer,args.session_id,input_kind=args.input_kind) if args.input=='-'
                    else ingest_file(box,args.input,args.session_id,input_kind=args.input_kind))
            emit({'state':'queued',**result});exit_code=0
        else:
            transport=LocalTransport(args.port)
            result=watch(box,args.session_id,transport,emit=emit) if args.watch else flush_once(box,args.session_id,transport,on_progress=emit)
            emit(result)
            exit_code=3 if result['state']=='blocked' else 75 if result['state'] in ('retry','waiting','batch_limit') else 0
        return exit_code
    except KeyboardInterrupt:
        emit({'state':'stopped','message':'Outbox retained; retries keep the original session and measurement IDs.'});return 130
    except (InputError,ValueError,OSError) as error:
        emit({'state':'error','error':type(error).__name__,'message':str(error),
              'queued_before_error':getattr(error,'queued',None),'line':getattr(error,'line',None)})
        return 2
    except (sqlite3.Error,ClaimLost) as error:
        emit({'state':'error','error':type(error).__name__,'message':str(error),
              'recovery':'Stop and inspect the outbox. Committed entries and original IDs are retained; a receipt not saved locally will be requested again after the lease expires.'})
        return 2
    finally:
        if box is not None: box.close()


if __name__=='__main__': raise SystemExit(main())
