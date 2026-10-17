import argparse
import yaml
import sys

POSITIONS_ORDER = ['GK', 'DF', 'MF', 'FW']


def load_yaml(path):
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def generate_field(data):
    rows = []
    game_id = data['game_id']
    date = data['date']
    match_type = data['match_type']
    venue = data['venue']
    win_team = data.get('win_team')

    num_quarters = len(data['quarters'])
    sorted_quarters = sorted(data['quarters'].keys())

    for qi, q_num in enumerate(sorted_quarters):
        q_data = data['quarters'][q_num]

        reserved_keys = {'goals', 'assists', 'referees', 'opponent_goals'}
        team_names = [k for k in q_data if k not in reserved_keys]

        # 외부 팀과의 경기: 상대 득점은 opponent_goals 로 받는다 (클린시트 계산용)
        external_goals = 0
        if data.get('opponent'):
            if q_data.get('opponent_goals') is None:
                print(f"경고: {q_num}쿼터 opponent_goals가 비어 있어 상대 득점을 0으로 봅니다", file=sys.stderr)
            external_goals = q_data.get('opponent_goals') or 0

        # Build player -> team mapping and ordered roster
        player_team = {}
        team_players_ordered = {}

        for team_name in team_names:
            team_players_ordered[team_name] = []
            roster = q_data[team_name]
            for pos in POSITIONS_ORDER:
                players = roster.get(pos, [])
                if isinstance(players, str):
                    players = [players]
                for p in players:
                    player_team[p] = team_name
                    team_players_ordered[team_name].append((pos, p))

        goals = q_data.get('goals', {}) or {}
        assists = q_data.get('assists', {}) or {}

        # Validate: check goal/assist players are in roster
        for player in goals:
            if player not in player_team:
                print(f"경고: '{player}'이(가) {q_num}쿼터 로스터에 없습니다 (골)", file=sys.stderr)
        for player in assists:
            if player not in player_team:
                print(f"경고: '{player}'이(가) {q_num}쿼터 로스터에 없습니다 (어시)", file=sys.stderr)

        # Goals per team (for CleanSheet calculation)
        team_goals_scored = {t: 0 for t in team_names}
        for player, g in goals.items():
            if player in player_team:
                team_goals_scored[player_team[player]] += g

        # Sort teams: losing team first, winning team second
        sorted_teams = sorted(team_names, key=lambda t: (1 if t == win_team else 0))

        # Generate player rows
        for team_name in sorted_teams:
            opponent_goals = external_goals + sum(
                team_goals_scored[t] for t in team_names if t != team_name
            )

            for pos, player in team_players_ordered[team_name]:
                win = 1 if team_name == win_team else 0
                goal = goals.get(player, 0)
                assist = assists.get(player, 0)
                clean_sheet = 1 if opponent_goals == 0 else 0

                rows.append([
                    game_id, date, team_name, player, match_type, q_num,
                    pos, win, goal, assist, clean_sheet, 0, 0, 1, venue, ''
                ])

        # Per-quarter referees
        for ref in q_data.get('referees', []):
            ref_name = ref['name']
            ref_team = ref['team']
            role = ref.get('role', 'main')

            if role == 'main':
                win = 1 if ref_team == win_team else 0
                referee_val, asst_val = 1, 0
            else:  # assistant
                win, referee_val, asst_val = 0, 0, 1

            rows.append([
                game_id, date, ref_team, ref_name, match_type, q_num,
                'Referee', win, 0, 0, 0, referee_val, asst_val, 1, venue, ''
            ])

        # Main referee (Q=1234) after first quarter block
        if qi == 0 and 'main_referee' in data:
            ref = data['main_referee']
            rows.append([
                game_id, date, ref['team'], ref['name'], match_type, 1234,
                'Referee', 0, 0, 0, 0, num_quarters, 0, 1, venue, ''
            ])

    return rows


def generate_futsal(data):
    rows = []
    game_id = data['game_id']
    date = data['date']
    venue = data['venue']

    for player, goals in data['players'].items():
        rows.append([
            game_id, date, 'null', player, '풋살', 'null',
            'null', 0, goals, 0, 0, 0, 0, 1, venue, ''
        ])

    return rows


def main():
    parser = argparse.ArgumentParser(description='AM6 RawSheet 데이터 생성기')
    parser.add_argument('yaml_file', help='게임 데이터 YAML 파일')
    parser.add_argument('-o', '--output', default=None, help='출력 파일 (기본: stdout)')
    parser.add_argument('--header', action='store_true', help='헤더 행 포함')
    args = parser.parse_args()

    data = load_yaml(args.yaml_file)

    if data['type'] == 'field':
        rows = generate_field(data)
    elif data['type'] == 'futsal':
        rows = generate_futsal(data)
    else:
        print(f"알 수 없는 타입: {data['type']}", file=sys.stderr)
        sys.exit(1)

    header = [
        'GameID', 'Date', 'Team', 'Player', 'MatchType', 'Quater',
        'Position', 'Win', 'Goal', 'Assist', 'CleanSheet',
        'Referee', 'Assistant Referee', 'Attendance', 'Venue', 'Etc.'
    ]

    lines = []
    if args.header:
        lines.append('\t'.join(header))
    for row in rows:
        lines.append('\t'.join(str(v) for v in row))

    output = '\n'.join(lines)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output + '\n')
        print(f'저장 완료: {args.output} ({len(rows)}행)', file=sys.stderr)
    else:
        print(output)
        print(f'\n총 {len(rows)}행 생성', file=sys.stderr)


if __name__ == '__main__':
    main()
