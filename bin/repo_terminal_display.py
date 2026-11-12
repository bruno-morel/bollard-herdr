"""Pass a viewer's palette to Herdr before an agent can query terminal colors."""
import json
import os
import re
import subprocess as sp

ENV = 'BOLLARD_TERMINAL_DISPLAY'


def display_from_env():
    raw = os.environ.get(ENV)
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {'fg', 'bg'} or not all(
        isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v)
        for v in value.values()
    ):
        raise ValueError('Invalid viewer terminal colors; reopen from the current window.')
    return value


def launch(argv, **kwargs):
    """Keep CLI behavior without a viewer palette. Never retry uncertain launches."""
    display = display_from_env()
    if not display:
        return sp.run(argv, **kwargs)
    args = [str(x) for x in argv]
    if args[:2] != ['hc', 'run']:
        raise ValueError('Expected a Herdr terminal launch')
    params = {'display': display, 'env': {ENV: json.dumps(display)}, 'wait': False}
    flags = {'--bg': ('wait', False), '--keep': ('keep', True),
             '--no-parent': ('no_parent', True), '--no-notify': ('no_notify', True),
             '--outlive-parent': ('outlive_parent', True), '--rm': ('rm', True)}
    values = {'--cwd': 'cwd', '--name': 'name', '--parent': 'parent', '--on': 'on'}
    i = 2
    while i < len(args) and args[i] != '--':
        option = args[i]
        if option in flags:
            key, value = flags[option]; params[key] = value; i += 1
        elif option in values or option == '--label':
            value = args[i + 1]; i += 2
            if option == '--label':
                key, value = value.split('=', 1)
                params.setdefault('labels', {})[key] = value
            else:
                params[values[option]] = value
        else:
            raise ValueError('Unsupported display-aware launch option: ' + option)
    if i == len(args):
        raise ValueError('Missing Herdr launch command separator')
    params['argv'] = args[i + 1:]
    # hc connect speaks newline-delimited JSON-RPC, including over SSH.
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'terminal.run', 'params': params}
    result = sp.run(['hc', 'connect'], input=json.dumps(request)+'\n',
                    capture_output=True, text=True, timeout=kwargs.get('timeout', 20),
                    cwd=kwargs.get('cwd'))
    if result.returncode:
        raise RuntimeError('Herdr launch was not confirmed; inspect hc ls --all before retrying. ' + result.stderr.strip())
    response = next((json.loads(line) for line in result.stdout.splitlines()
                     if line.strip() and json.loads(line).get('id') == 1), None)
    if not response or 'error' in response or 'result' not in response:
        raise RuntimeError('Herdr launch was not confirmed; inspect hc ls --all before retrying. ' + str(response))
    return sp.CompletedProcess(args, 0)
