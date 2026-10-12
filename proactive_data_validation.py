#!/usr/bin/env python3
"""Read-only SAP/IQ production order reconciliation using CSV exports.

Usage:
  python proactive_data_validation.py --sap sap_orders.csv --iq iq_orders.csv

Expected SAP columns: order_id,status,scheduled_at
Expected IQ columns: order_id,status,scheduled_at
Optional columns: updated_at (both), source_event_id (IQ)
Timestamps: ISO 8601, e.g. 2026-10-12T23:00:00-04:00.
"""
import argparse
import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

SAP_READY = {'RELEASED', 'READY', 'CREATED'}
IQ_READY = {'QUEUED', 'READY', 'RUNNING', 'COMPLETED'}
IQ_PENDING = {'PENDING', 'PROCESSING', 'REPROCESSING', 'FAILED', 'ERROR', 'HELD'}


def timestamp(value):
    if not value or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError(f'Timestamp needs timezone offset: {value!r}')
    return parsed.astimezone(timezone.utc)


def load_orders(path):
    with open(path, newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        required = {'order_id', 'status', 'scheduled_at'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f'{path}: required columns: {sorted(required)}')
        result = {}
        duplicates = set()
        for line, row in enumerate(reader, 2):
            order_id = (row.get('order_id') or '').strip()
            if not order_id:
                raise ValueError(f'{path}:{line}: missing order_id')
            if order_id in result:
                duplicates.add(order_id)
                continue
            row['status'] = (row.get('status') or '').strip().upper()
            row['scheduled_at_parsed'] = timestamp(row.get('scheduled_at'))
            row['updated_at_parsed'] = timestamp(row.get('updated_at'))
            result[order_id] = row
        if duplicates:
            raise ValueError(f'{path}: duplicate order IDs (review before reconciliation): {sorted(duplicates)}')
        return result


def exception(order_id, code, severity, sap, iq, message, action):
    return {
        'order_id': order_id, 'code': code, 'severity': severity,
        'sap_status': sap.get('status', '') if sap else '',
        'iq_status': iq.get('status', '') if iq else '',
        'sap_scheduled_at': sap.get('scheduled_at', '') if sap else '',
        'iq_scheduled_at': iq.get('scheduled_at', '') if iq else '',
        'message': message, 'recommended_action': action,
    }


def reconcile(sap_orders, iq_orders, now, grace_minutes, schedule_tolerance_minutes):
    issues = []
    grace = timedelta(minutes=grace_minutes)
    tolerance = timedelta(minutes=schedule_tolerance_minutes)
    for order_id in sorted(set(sap_orders) | set(iq_orders)):
        sap = sap_orders.get(order_id)
        iq = iq_orders.get(order_id)
        if not sap:
            issues.append(exception(order_id, 'IQ_ONLY_ORDER', 'WARNING', sap, iq,
                'Order exists in IQ export but not SAP export.',
                'Check export scope, order mapping, and whether the SAP record was archived.'))
            continue
        if not iq:
            scheduled = sap['scheduled_at_parsed']
            if sap['status'] in SAP_READY and scheduled and now >= scheduled - grace:
                severity = 'CRITICAL' if now >= scheduled else 'WARNING'
                issues.append(exception(order_id, 'MISSING_IN_IQ', severity, sap, iq,
                    'SAP order is ready but missing from the IQ export near or after its scheduled time.',
                    'Check integration delivery, IQ ingestion/reprocessing logs, and queue assignment.'))
            continue
        sap_time = sap['scheduled_at_parsed']
        iq_time = iq['scheduled_at_parsed']
        if sap_time and iq_time and abs(sap_time - iq_time) > tolerance:
            issues.append(exception(order_id, 'SCHEDULE_MISMATCH', 'WARNING', sap, iq,
                'SAP and IQ scheduled times differ beyond the configured tolerance.',
                'Verify approved schedule changes, timezone handling, and synchronization.'))
        if sap['status'] in SAP_READY and iq['status'] in IQ_PENDING:
            # Grace window avoids flagging expected synchronization delays too early.
            reference = sap_time or sap['updated_at_parsed']
            if reference and now >= reference - grace:
                severity = 'CRITICAL' if sap_time and now >= sap_time else 'WARNING'
                issues.append(exception(order_id, 'IQ_NOT_READY', severity, sap, iq,
                    'SAP order is ready, but IQ is not in a ready/running/completed state.',
                    'Inspect IQ status and reprocessing history; confirm queue position with support.'))
        elif sap['status'] in SAP_READY and iq['status'] not in IQ_READY and iq['status'] not in IQ_PENDING:
            issues.append(exception(order_id, 'UNKNOWN_IQ_STATUS', 'WARNING', sap, iq,
                'Unrecognized IQ status; cannot determine readiness.',
                'Confirm IQ status mapping with the application owner.'))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sap', required=True, type=Path)
    parser.add_argument('--iq', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('validation_exceptions.csv'))
    parser.add_argument('--grace-minutes', type=int, default=30)
    parser.add_argument('--schedule-tolerance-minutes', type=int, default=5)
    parser.add_argument('--now', help='ISO 8601 timestamp for testing; defaults to current time')
    args = parser.parse_args()
    if args.grace_minutes < 0 or args.schedule_tolerance_minutes < 0:
        parser.error('Grace and tolerance must be nonnegative')
    try:
        now = timestamp(args.now) if args.now else datetime.now(timezone.utc)
        sap = load_orders(args.sap)
        iq = load_orders(args.iq)
        issues = reconcile(sap, iq, now, args.grace_minutes, args.schedule_tolerance_minutes)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    fields = ['order_id', 'code', 'severity', 'sap_status', 'iq_status',
              'sap_scheduled_at', 'iq_scheduled_at', 'message', 'recommended_action']
    with args.output.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(issues)
    print(json.dumps({'sap_orders': len(sap), 'iq_orders': len(iq),
                      'exceptions': len(issues), 'output': str(args.output)}, indent=2))
    for issue in issues:
        print(f"[{issue['severity']}] {issue['order_id']}: {issue['code']} - {issue['message']}")


if __name__ == '__main__':
    main()
