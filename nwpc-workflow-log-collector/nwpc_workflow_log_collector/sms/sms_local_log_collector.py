# coding: utf-8
import datetime
import json

import click
import yaml

from nwpc_workflow_log_model.rmdb.util.session import get_session
from nwpc_workflow_log_model.rmdb.sms.record import SmsRecord
from nwpc_workflow_log_model.rmdb.util.version_util import VersionUtil

from nwpc_workflow_log_collector.sms.util.log_file_util import SmsLogFileUtil


def load_config(config_file_path):
    f = open(config_file_path, 'r')
    config = yaml.load(f)
    f.close()
    return config


def get_log_info_from_local_file(config_object: dict, owner: str, repo: str, log_file: str, output_type):
    with open(log_file) as f:
        first_line = f.readline()
        if first_line is None:
            return {
                'file_path': log_file,
                'line_count': 0
            }
        first_record = SmsRecord()
        first_record.parse(first_line)

        cur_line_no = 1
        cur_line = first_line
        for line in f:
            cur_line = line
            cur_line_no += 1
        last_record = SmsRecord()
        last_record.parse(cur_line)
        return {
            'file_path': log_file,
            'line_count': cur_line_no,
            'range': {
                'start': {
                    'date': first_record.date.strftime('%Y-%m-%d'),
                    'time': first_record.time.strftime('%H:%M:%S')
                },
                'end': {
                    'date': last_record.date.strftime('%Y-%m-%d'),
                    'time': last_record.time.strftime('%H:%M:%S')
                }
            }
        }


def collect_log_from_local_file(config: dict, owner_name: str, repo_name: str, file_path: str, verbose):
    session = get_session(config['smslog_local_collector']['rdbms']['database_uri'])

    with open(file_path) as f:
        first_line = f.readline().strip()
        version = VersionUtil.get_version(session, owner_name, repo_name, file_path, first_line, SmsRecord)
        SmsRecord.prepare(owner_name, repo_name)

        query = session.query(SmsRecord).filter(SmsRecord.repo_id == version.repo_id) \
            .filter(SmsRecord.version_id == version.version_id) \
            .order_by(SmsRecord.line_no.desc()) \
            .limit(1)

        latest_record = query.first()
        if latest_record is None:
            start_line_no = 0
        else:
            start_line_no = latest_record.line_no + 1

        if start_line_no == 0:
            record = SmsRecord()
            record.parse(first_line)
            record.repo_id = version.repo_id
            record.version_id = version.version_id
            record.line_no = 0
            session.add(record)
            start_line_no += 1

        for i in range(1, start_line_no):
            f.readline()

        session_count_to_be_committed = 0

        cur_line_no = start_line_no
        commit_begin_line_no = cur_line_no
        for line in f:
            line = line.strip()
            if line[0] != '#':
                cur_line_no += 1
                continue
            record = SmsRecord()
            if verbose > 1:
                print(cur_line_no, line)
            record.parse(line)
            record.repo_id = version.repo_id
            record.version_id = version.version_id
            record.line_no = cur_line_no
            session.add(record)
            cur_line_no += 1

            session_count_to_be_committed += 1
            if session_count_to_be_committed >= config['smslog_local_collector']['sms']['post']['max_count']:
                commit_end_line_no = cur_line_no
                session.commit()
                click.echo('[{time}] commit session, line range: [{begin_line_no}, {end_line_no}]'.format(
                    time=datetime.datetime.now(),
                    begin_line_no=commit_begin_line_no,
                    end_line_no=commit_end_line_no
                ))
                session_count_to_be_committed = 0
                commit_begin_line_no = cur_line_no + 1

        if session_count_to_be_committed > 0:
            session.commit()
            click.echo('commit session, last lines.')


def collect_log_from_local_file_by_range(config: dict, owner_name: str, repo_name: str, file_path: str,
                                         start_date, end_date, verbose):
    session = get_session(config['sms_local_log_collector']['rdbms']['database_uri'])

    with open(file_path) as f:
        first_line = f.readline().strip()
        version = VersionUtil.get_version(session, owner_name, repo_name, file_path, first_line, SmsRecord)
        SmsRecord.prepare(owner_name, repo_name)

        print("Finding line no in range:", start_date, end_date)
        begin_line_no, end_line_no = SmsLogFileUtil.get_line_no_range(
            file_path,
            datetime.datetime.strptime(start_date, "%Y-%m-%d").date(),
            datetime.datetime.strptime(end_date, "%Y-%m-%d").date())
        if begin_line_no == 0 or end_line_no == 0:
            click.echo("line not found")
            return
        print("Found line no in range:", begin_line_no, end_line_no)

        for i in range(1, begin_line_no):
            f.readline()

        session_count_to_be_committed = 0
        max_count = config['smslog_local_collector']['sms']['post']['max_count']
        # max_count = 1

        cur_line_no = begin_line_no
        commit_begin_line_no = cur_line_no
        for i in range(begin_line_no, end_line_no):
            line = f.readline()
            line = line.strip()
            if len(line) == 0 or line[0] != '#':
                cur_line_no += 1
                continue
            record = SmsRecord()
            if verbose > 1:
                print(cur_line_no, line)
            record.parse(line)
            record.repo_id = version.repo_id
            record.version_id = version.version_id
            record.line_no = cur_line_no
            record = session.add(record)
            cur_line_no += 1

            session_count_to_be_committed += 1
            if session_count_to_be_committed >= max_count:
                commit_end_line_no = cur_line_no
                session.commit()
                click.echo('[{time}] commit session, line range: [{begin_line_no}, {end_line_no}]'.format(
                    time=datetime.datetime.now(),
                    begin_line_no=commit_begin_line_no,
                    end_line_no=commit_end_line_no
                ))
                session_count_to_be_committed = 0
                commit_begin_line_no = cur_line_no + 1

        if session_count_to_be_committed > 0:
            session.commit()
            click.echo('commit session, last lines.')


@click.group()
def cli():
    pass


@cli.command()
@click.option('-c', '--config', help='config file path')
@click.option('-o', '--owner', help='owner name')
@click.option('-r', '--repo', help='repo name')
@click.option('-l', '--log-file', help='log file path')
@click.option('--output-type', type=click.Choice(['print', 'json']), default='json', help='output type')
def info(config, owner, repo, log_file, output_type):
    config_object = load_config(config)
    log_info = get_log_info_from_local_file(config_object, owner, repo, log_file, output_type)
    result = {
        'app': 'sms_local_collector',
        'timestamp': datetime.datetime.now().timestamp(),
        'data': {
            'log_info': log_info
        }
    }
    print(json.dumps(result, indent=2))


@cli.command()
@click.option('-c', '--config', help='config file path')
@click.option('-o', '--owner', help='owner name')
@click.option('-r', '--repo', help='repo name')
@click.option('-l', '--log-file', help='log file path')
@click.option('-v', '--verbose', count=True, help='verbose level')
def load(config, owner, repo, log_file, verbose):
    config_object = load_config(config)
    collect_log_from_local_file(config_object, owner, repo, log_file, verbose)


@cli.command()
@click.option('-c', '--config', help='config file path')
@click.option('-o', '--owner', help='owner name')
@click.option('-r', '--repo', help='repo name')
@click.option('-l', '--log-file', help='log file path')
@click.option('--begin-date', help='begin date, [start_date, end_date), YYYY-MM-dd')
@click.option('--end-date', help='end date, [start_date, end_date), YYYY-MM-dd')
@click.option('-v', '--verbose', count=True, help='verbose level')
def load_range(config, owner, repo, log_file, begin_date, end_date, verbose):
    config_object = load_config(config)
    collect_log_from_local_file_by_range(config_object, owner, repo, log_file, begin_date, end_date, verbose)


if __name__ == "__main__":
    cli()