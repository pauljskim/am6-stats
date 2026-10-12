"""
AM6 시즌 기록 → 통계 계산 → 정적 웹페이지 생성

    python3 am6.py build                 # public/ 에 사이트 생성 (모든 시즌)
    python3 am6.py new futsal 2026-10-17 # 현재 시즌 games/에 다음 라운드 YAML 생성
    python3 am6.py new field 2026-10-24
    python3 am6.py season 26-27          # 새 시즌 폴더 생성 (회원·가중치는 직전 시즌에서 복사)
    python3 am6.py tsv <game.yaml>       # 예전처럼 시트 붙여넣기용 TSV 출력

데이터 위치:
    seasons/<시즌>/config.yaml   회원 명단, 가중치
    seasons/<시즌>/history.tsv   (선택) 구글 시트에서 옮겨온 과거 기록
    seasons/<시즌>/games/*.yaml  경기 기록. history.tsv에 이미 있는 GameID는 무시
"""
import argparse
import collections
import csv
import datetime
import glob
import json
import os
import re
import shutil
import sys

import yaml

from generate_raw import generate_field, generate_futsal

ROOT = os.path.dirname(os.path.abspath(__file__))
SEASONS_DIR = os.path.join(ROOT, 'seasons')
OUT_DIR = os.path.join(ROOT, 'public')
TEMPLATE = os.path.join(ROOT, 'site', 'template.html')

FIELD_TYPES = ['8:8', '9:9', '11:11']
FUTSAL = '풋살'


# ── 데이터 로드 ──────────────────────────────────────────────────────────

def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _norm(v):
    s = '' if v is None else str(v).strip()
    return '' if s in ('None', 'null') else s


def make_row(gid, date, team, player, mt, q, pos, win, goal, assist, cs,
             ref, aref, att, venue, etc):
    q = _norm(q)
    return {
        'gid': _norm(gid), 'date': _norm(date), 'team': _norm(team),
        'player': _norm(player), 'mt': _norm(mt),
        'q': _int(q) if q else None, 'pos': _norm(pos),
        'win': _int(win), 'goal': _int(goal), 'assist': _int(assist),
        'cs': _int(cs), 'ref': _int(ref), 'aref': _int(aref),
        'att': _int(att), 'venue': _norm(venue), 'etc': _norm(etc),
    }


def load_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def yaml_rows(data):
    data = dict(data)
    if data.get('quarters'):
        data['quarters'] = {k: v for k, v in data['quarters'].items() if v}
    if _norm(data.get('win_team')) == '':
        data['win_team'] = None
    if data['type'] == 'field':
        raw = generate_field(data)
    elif data['type'] == 'futsal':
        raw = generate_futsal(data)
    else:
        raise ValueError('알 수 없는 type: %s' % data['type'])
    rows = [make_row(*r) for r in raw]
    if data.get('opponent'):
        for r in rows:
            r['etc'] = r['etc'] or '(vs %s)' % data['opponent']
    return rows


def load_season(season):
    sdir = os.path.join(SEASONS_DIR, season)
    config = load_yaml(os.path.join(sdir, 'config.yaml'))
    rows = []
    hist = os.path.join(sdir, 'history.tsv')
    if os.path.exists(hist):
        with open(hist, encoding='utf-8') as f:
            for r in csv.DictReader(f, delimiter='\t'):
                rows.append(make_row(*[r[k] for k in (
                    'GameID', 'Date', 'Team', 'Player', 'MatchType', 'Quater',
                    'Position', 'Win', 'Goal', 'Assist', 'CleanSheet', 'Referee',
                    'Assistant Referee', 'Attendance', 'Venue', 'Etc.')]))
    known = set(r['gid'] for r in rows)
    for path in sorted(glob.glob(os.path.join(sdir, 'games', '*.yaml'))):
        data = load_yaml(path)
        if not data or 'XX' in str(data.get('game_id', 'XX')):
            continue
        if data['game_id'] in known:
            continue
        name = os.path.relpath(path, ROOT)
        if data.get('draft'):
            print('  건너뜀 (draft: true): %s' % name, file=sys.stderr)
            continue
        try:
            rows.extend(yaml_rows(data))
        except Exception as e:
            sys.exit('YAML 오류 %s: %r' % (name, e))
        known.add(data['game_id'])
    rows = [r for r in rows if r['gid'] and r['player']]
    return config, rows


def list_seasons():
    if not os.path.isdir(SEASONS_DIR):
        return []
    return sorted(d for d in os.listdir(SEASONS_DIR)
                  if os.path.exists(os.path.join(SEASONS_DIR, d, 'config.yaml')))


def round_no(gid):
    m = re.search(r'Round\s*(\d+)', gid, re.I)
    return int(m.group(1)) if m else 0


# ── 통계 ────────────────────────────────────────────────────────────────

def ranked(values, keep_zero=False):
    """{이름: 값} → [(순위, 이름, 값)], 동점은 같은 순위 (1,1,3...)"""
    items = sorted(((n, v) for n, v in values.items() if keep_zero or v > 0),
                   key=lambda x: (-x[1], x[0]))
    out, prev_v, prev_rank = [], None, 0
    for i, (n, v) in enumerate(items):
        rank = prev_rank if v == prev_v else i + 1
        out.append((rank, n, v))
        prev_v, prev_rank = v, rank
    return out


def player_stats(rows, config):
    """구글 시트 Summary_sheet 수식과 동일한 방식으로 선수별 누적 기록 계산"""
    w = config['weights']
    gids = set(r['gid'] for r in rows)
    total_games = len(gids)

    P = collections.defaultdict(lambda: {
        'games': set(), 'ref': 0, 'aref': 0, 'quarters': 0, 'cs_q': 0,
        'by': {mt: {'win': 0, 'goal': 0, 'assist': 0, 'cs': 0, 'games': 0}
               for mt in [FUTSAL] + FIELD_TYPES},
        'field_wins': 0,
    })
    win_by_game = collections.defaultdict(int)       # (player, mt, gid) → max(Win)
    qtr_wins = collections.defaultdict(list)          # 최다승: 쿼터 과반 승리 판정용
    has_1234 = {}

    for r in rows:
        p = P[r['player']]
        mt = r['mt']
        if r['att'] == 1:
            p['games'].add(r['gid'])
        p['ref'] += r['ref']
        p['aref'] += r['aref']
        if mt in p['by']:
            b = p['by'][mt]
            b['goal'] += r['goal']
            b['assist'] += r['assist']
            b['cs'] += r['cs']
            k = (r['player'], mt, r['gid'])
            win_by_game[k] = max(win_by_game[k], r['win'])
        if mt != FUTSAL and r['pos'] != 'Referee' and r['q'] is not None:
            p['quarters'] += 1
            p['cs_q'] += r['cs']
            k = (r['player'], r['gid'])
            if r['q'] == 1234:
                has_1234[k] = r['win']
            else:
                qtr_wins[k].append(r['win'])

    for (player, mt, gid), v in win_by_game.items():
        P[player]['by'][mt]['win'] += v
        P[player]['by'][mt]['games'] += 1
    for k in set(qtr_wins) | set(has_1234):
        q = qtr_wins.get(k)
        won = sum(q) > len(q) / 2 if q else has_1234.get(k) == 1
        if won:
            P[k[0]]['field_wins'] += 1

    keymap = {'win': 'win', 'goal': 'goal', 'assist': 'assist', 'clean_sheet': 'cs'}
    for adj in config.get('adjustments') or []:      # 시트에서 손으로 고쳤던 값 등 수동 보정
        if adj['name'] not in P:
            continue
        for mt, fields in adj.items():
            if mt in P[adj['name']]['by']:
                for k, v in fields.items():
                    P[adj['name']]['by'][mt][keymap[k]] += v

    out = {}
    for name, p in P.items():
        att = len(p['games'])
        pts = att * w['attendance'] + p['ref'] * w['referee'] + p['aref'] * w['assistant_referee']
        for mt, b in p['by'].items():
            mw = w.get(mt, {})
            pts += sum(b[k] * mw.get(wk, 0) for k, wk in
                       (('win', 'win'), ('goal', 'goal'), ('assist', 'assist'), ('cs', 'clean_sheet')))
        field = {k: sum(p['by'][mt][k] for mt in FIELD_TYPES) for k in ('win', 'goal', 'assist', 'cs', 'games')}
        out[name] = {
            'points': pts, 'att': att, 'att_rate': att / total_games if total_games else 0,
            'ref': p['ref'], 'aref': p['aref'], 'quarters': p['quarters'],
            'cs_q': p['cs_q'], 'field_wins': p['field_wins'],
            'futsal_win': p['by'][FUTSAL]['win'],
            'futsal_goal': p['by'][FUTSAL]['goal'], 'futsal_games': p['by'][FUTSAL]['games'],
            'field_goal': field['goal'], 'field_assist': field['assist'], 'field_games': field['games'],
            'by': {mt: p['by'][mt] for mt in FIELD_TYPES},
        }
    return out, total_games


BOARDS = [
    # key, 제목, 단위, 값 함수, 회원만
    ('power', '파워랭킹', 'pt', lambda s: s['points'], True),
    ('att', '출장', '경기', lambda s: s['att'], False),
    ('futsal_goal', '풋살 득점', '골', lambda s: s['futsal_goal'], False),
    ('field_goal', '필드 득점', '골', lambda s: s['field_goal'], False),
    ('field_assist', '필드 도움', '도움', lambda s: s['field_assist'], False),
    ('attack', '공격 포인트', '골+도움', lambda s: s['field_goal'] + s['field_assist'], False),
    ('cs', '클린시트', '쿼터', lambda s: s['cs_q'], False),
    ('wins', '최다승', '승', lambda s: s['field_wins'], False),
    ('quarters', '쿼터 출전', '쿼터', lambda s: s['quarters'], False),
]


def boards(stats, members):
    res = {}
    for key, _, _, fn, member_only in BOARDS:
        vals = {n: fn(s) for n, s in stats.items() if not member_only or n in members}
        res[key] = ranked(vals, keep_zero=member_only)
    return res


def game_summaries(rows):
    by_gid = collections.OrderedDict()
    for r in rows:
        by_gid.setdefault(r['gid'], []).append(r)

    games = []
    for gid, rs in by_gid.items():
        mt = next((r['mt'] for r in rs if r['mt']), '')
        g = {
            'id': gid, 'round': round_no(gid), 'date': rs[0]['date'], 'type': mt,
            'venue': next((r['venue'] for r in rs if r['venue']), ''),
            'attendees': sorted(set(r['player'] for r in rs if r['att'] == 1)),
            'note': next((r['etc'] for r in rs if r['etc']), ''),
        }
        goals = collections.Counter()
        assists = collections.Counter()
        for r in rs:
            goals[r['player']] += r['goal']
            assists[r['player']] += r['assist']
        g['scorers'] = [[n, c] for n, c in sorted(goals.items(), key=lambda x: (-x[1], x[0])) if c]
        g['assists'] = [[n, c] for n, c in sorted(assists.items(), key=lambda x: (-x[1], x[0])) if c]
        g['total_goals'] = sum(goals.values())

        if mt != FUTSAL:
            play = [r for r in rs if r['pos'] != 'Referee' and r['team']]
            teams = []
            for r in play:
                if r['team'] not in teams:
                    teams.append(r['team'])
            qs = sorted(set(r['q'] for r in play if r['q'] not in (None, 1234)))
            team_info = []
            for t in teams:
                tr = [r for r in play if r['team'] == t]
                team_info.append({
                    'name': t,
                    'goals': sum(r['goal'] for r in tr),
                    'win': any(r['win'] for r in tr),
                    'quarters': [sum(r['goal'] for r in tr if r['q'] == q) for q in qs],
                    'players': sorted(set(r['player'] for r in tr)),
                })
            m = re.search(r'vs\s*([^)\s]+)', g['note'])
            if len(team_info) == 1 and m:
                team_info.append({'name': m.group(1), 'goals': None, 'win': False,
                                  'quarters': [None] * len(qs), 'players': [], 'external': True})
            g['teams'] = team_info
            g['quarters'] = qs
            refs = []
            for r in rs:
                if r['pos'] == 'Referee':
                    role = '부심' if r['aref'] else '주심'
                    when = '전체' if r['q'] == 1234 else ('%dQ' % r['q'] if r['q'] else '')
                    refs.append([r['player'], role, when])
            g['referees'] = refs
        games.append(g)
    games.sort(key=lambda g: (g['date'], g['round']))
    return games


def player_logs(rows, games):
    """선수별 경기 로그"""
    logs = collections.defaultdict(list)
    by = collections.defaultdict(list)
    for r in rows:
        by[(r['player'], r['gid'])].append(r)
    for g in games:
        for (player, gid), rs in by.items():
            if gid != g['id']:
                continue
            play = [r for r in rs if r['pos'] != 'Referee']
            logs[player].append({
                'gid': gid,
                'team': next((r['team'] for r in play if r['team']), ''),
                'goal': sum(r['goal'] for r in rs),
                'assist': sum(r['assist'] for r in rs),
                'quarters': len([r for r in play if r['q'] not in (None, 1234)]),
                'cs': sum(r['cs'] for r in play),
                'win': max([r['win'] for r in play] or [0]),
                'ref': sum(r['ref'] + r['aref'] for r in rs),
                'pos': sorted(set(r['pos'] for r in play if r['pos'])),
            })
    return logs


SYNERGY_MIN_Q = 3   # 이 쿼터 수 이상 함께 뛴 조합만 '신뢰 조합'


def synergy(rows, member_names):
    """같은 쿼터·같은 팀으로 뛴 회원 두 명의 궁합 (기존 synergy_matrix.py와 같은 계산)

    점수 = (승률 + 쿼터당 두 선수 공격포인트 + 무실점률) / 3 을
    신뢰 조합(3쿼터 이상)과 참고 조합(1~2쿼터) 각각 안에서 1~5점으로 정규화
    """
    groups = collections.OrderedDict()            # (gid, q) → {team: [row]}
    for r in rows:
        if r['mt'] in ('', FUTSAL) or r['pos'] in ('Referee', 'Assistant Referee'):
            continue
        if not (r['player'] and r['team']) or r['q'] is None or r['player'] not in member_names:
            continue
        groups.setdefault((r['gid'], r['q']), collections.OrderedDict()) \
              .setdefault(r['team'], []).append(r)

    apps = collections.OrderedDict()
    stat = collections.defaultdict(lambda: [0, 0, 0, 0])   # 쿼터, 승, 골+도움, 무실점
    for teams in groups.values():
        seen = set()
        for plist in teams.values():
            for r in plist:
                if r['player'] not in seen:
                    apps[r['player']] = apps.get(r['player'], 0) + 1
                    seen.add(r['player'])
            for i in range(len(plist)):
                for j in range(i + 1, len(plist)):
                    a, b = plist[i], plist[j]
                    st = stat[tuple(sorted((a['player'], b['player'])))]
                    st[0] += 1
                    st[1] += 1 if a['win'] == 1 else 0
                    st[2] += a['goal'] + b['goal'] + a['assist'] + b['assist']
                    st[3] += 1 if a['cs'] == 1 else 0

    raw = {pair: (st[1] / st[0] + st[2] / st[0] + st[3] / st[0]) / 3.0 for pair, st in stat.items()}

    def scale(pairs):
        if not pairs:
            return {}
        lo, hi = min(raw[p] for p in pairs), max(raw[p] for p in pairs)
        return {p: 3 if hi == lo else int(round(1 + (raw[p] - lo) / (hi - lo) * 4)) for p in pairs}

    score = scale([p for p in stat if stat[p][0] >= SYNERGY_MIN_Q])
    score.update(scale([p for p in stat if stat[p][0] < SYNERGY_MIN_Q]))

    names = sorted(apps, key=lambda n: -apps[n])
    idx = {n: i for i, n in enumerate(names)}
    pairs = [[idx[a], idx[b], score[(a, b)], int(stat[(a, b)][0] < SYNERGY_MIN_Q)] + stat[(a, b)]
             for a, b in sorted(stat, key=lambda p: (idx[p[0]], idx[p[1]]))]
    return {'players': names, 'apps': [apps[n] for n in names], 'pairs': pairs,
            'quarters': len(groups), 'min_q': SYNERGY_MIN_Q}


def delta(cur_rank, prev_map, name):
    if name not in prev_map:
        return 'new'
    return prev_map[name] - cur_rank


def season_payload(season, config, rows):
    members = collections.OrderedDict((m['name'], m) for m in config.get('members', []))
    stats, total_games = player_stats(rows, config)
    games = game_summaries(rows)
    cur_boards = boards(stats, members)

    latest = max(r['date'] for r in rows) if rows else None
    prev_rows = [r for r in rows if r['date'] != latest]
    prev_boards = {}
    if prev_rows:
        prev_stats, _ = player_stats(prev_rows, config)
        prev_boards = boards(prev_stats, members)

    out_boards = []
    for key, title, unit, _, member_only in BOARDS:
        pm = {n: rk for rk, n, _ in prev_boards.get(key, [])}
        out_boards.append({
            'key': key, 'title': title, 'unit': unit, 'member_only': member_only,
            'rows': [[rk, n, v, delta(rk, pm, n) if prev_rows else None]
                     for rk, n, v in cur_boards[key]],
        })

    power_rank = {n: rk for rk, n, _ in cur_boards['power']}
    prev_power = {n: rk for rk, n, _ in prev_boards.get('power', [])}
    logs = player_logs(rows, games)
    players = []
    for name, s in stats.items():
        m = members.get(name)
        players.append(dict(s, name=name, member=bool(m),
                            no=str(m.get('number', '')) if m else '',
                            status=m.get('status', '') if m else '게스트',
                            rank=power_rank.get(name), prev_rank=prev_power.get(name),
                            log=logs.get(name, [])))
    for name, m in members.items():   # 기록 없는 회원도 명단에 포함
        if name not in stats:
            players.append({'name': name, 'member': True, 'no': str(m.get('number', '')),
                            'status': m.get('status', ''), 'points': 0, 'att': 0,
                            'att_rate': 0, 'rank': power_rank.get(name), 'log': []})
    players.sort(key=lambda p: (-p.get('points', 0), p['name']))

    venues = collections.Counter(g['venue'] for g in games if g['venue'])
    regular = set(n for n, m in members.items() if m.get('status', '정회원') == '정회원')
    return {
        'season': season,
        'period': config.get('period', ''),
        'team': config.get('team_name', 'AM6'),
        'weights': config['weights'],
        'total_games': total_games,
        'latest': latest,
        'boards': out_boards,
        'games': games,
        'players': players,
        'venues': venues.most_common(),
        'synergy': synergy(rows, regular),
        'built_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


# ── 사이트 생성 ──────────────────────────────────────────────────────────

def render(payload, seasons, base):
    with open(TEMPLATE, encoding='utf-8') as f:
        html = f.read()
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    nav = json.dumps({'seasons': seasons, 'current': payload['season'], 'base': base},
                     ensure_ascii=False)
    return (html.replace('/*__DATA__*/null', data)
                .replace('/*__NAV__*/null', nav)
                .replace('__TITLE__', '%s %s 시즌 기록' % (payload['team'], payload['season'])))


def cmd_build(args):
    seasons = list_seasons()
    if not seasons:
        sys.exit('seasons/ 폴더에 시즌이 없습니다.')
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR)
    for s in seasons:
        config, rows = load_season(s)
        payload = season_payload(s, config, rows)
        os.makedirs(os.path.join(OUT_DIR, s))
        with open(os.path.join(OUT_DIR, s, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(render(payload, seasons, '../'))
        print('%s: %d경기, %d행 → public/%s/' % (s, payload['total_games'], len(rows), s))
        if s == seasons[-1]:
            with open(os.path.join(OUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
                f.write(render(payload, seasons, './'))
    with open(os.path.join(OUT_DIR, '.nojekyll'), 'w'):
        pass
    print('완료: public/index.html (현재 시즌 %s)' % seasons[-1])


def cmd_new(args):
    season = args.season or list_seasons()[-1]
    sdir = os.path.join(SEASONS_DIR, season)
    _, rows = load_season(season)
    next_round = max([round_no(r['gid']) for r in rows] or [0]) + 1
    date = args.date or datetime.date.today().isoformat()
    tpl = os.path.join(ROOT, 'template', 'template_%s.yaml' % args.type)
    with open(tpl, encoding='utf-8') as f:
        text = f.read()
    text = re.sub(r'game_id: ".*?"', 'game_id: "%s Round %d"' % (season, next_round), text)
    text = re.sub(r'date: ".*?"', 'date: "%s"' % date, text)
    text = ('# 작성이 끝나면 아래 draft 줄을 지우세요. 지우기 전에는 사이트에 반영되지 않습니다.\n'
            'draft: true\n\n' + text)
    path = os.path.join(sdir, 'games', '%s_%s.yaml' % (date.replace('-', ''), args.type))
    if os.path.exists(path):
        sys.exit('이미 있습니다: %s' % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print('생성: %s (Round %d)' % (os.path.relpath(path, ROOT), next_round))


def cmd_season(args):
    sdir = os.path.join(SEASONS_DIR, args.name)
    if os.path.exists(sdir):
        sys.exit('이미 있습니다: %s' % sdir)
    prev = list_seasons()
    os.makedirs(os.path.join(sdir, 'games'))
    cfg = {}
    if prev:
        cfg = load_yaml(os.path.join(SEASONS_DIR, prev[-1], 'config.yaml'))
    cfg['season'] = args.name
    cfg['period'] = args.period or ''
    with open(os.path.join(sdir, 'config.yaml'), 'w', encoding='utf-8') as f:
        f.write('# %s 시즌 설정 (%s 시즌에서 복사됨 — 회원 명단·가중치를 확인하세요)\n'
                % (args.name, prev[-1] if prev else '-'))
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=None)
    print('생성: seasons/%s/ — config.yaml 확인 후 games/에 경기 추가' % args.name)


def cmd_tsv(args):
    data = load_yaml(args.yaml_file)
    raw = generate_field(data) if data['type'] == 'field' else generate_futsal(data)
    for r in raw:
        print('\t'.join(str(v) for v in r))


def main():
    ap = argparse.ArgumentParser(description='AM6 시즌 기록 관리')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('build', help='웹페이지 생성')
    p = sub.add_parser('new', help='다음 라운드 YAML 생성')
    p.add_argument('type', choices=['field', 'futsal'])
    p.add_argument('date', nargs='?', help='YYYY-MM-DD (기본: 오늘)')
    p.add_argument('--season')
    p = sub.add_parser('season', help='새 시즌 시작')
    p.add_argument('name', help='예: 26-27')
    p.add_argument('--period', help='예: "2026.12 – 2027.11"')
    p = sub.add_parser('tsv', help='YAML → 시트 붙여넣기용 TSV')
    p.add_argument('yaml_file')
    args = ap.parse_args()
    {'build': cmd_build, 'new': cmd_new, 'season': cmd_season, 'tsv': cmd_tsv}.get(
        args.cmd, lambda a: ap.print_help())(args)


if __name__ == '__main__':
    main()
