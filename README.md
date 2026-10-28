# AM6 시즌 기록

경기마다 YAML 파일 하나를 쓰면 통계를 계산하고 웹페이지를 만든다.
GitHub에 push하면 GitHub Pages에 자동으로 배포된다. 구글 시트와 Apps Script는 더 쓰지 않아도 된다.

## 폴더 구성

```
seasons/
  25-26/
    config.yaml      회원 명단, 포인트 가중치, 수동 보정
    history.tsv      구글 시트 RawSheet에서 옮겨온 R1~R32 (고정, 수정하지 않음)
    games/*.yaml     경기 기록 (history.tsv에 이미 있는 라운드는 무시됨)
  26-27/             다음 시즌 (python3 am6.py season 26-27 로 생성)
template/            YAML 템플릿
site/template.html   웹페이지 디자인
am6.py               명령어 모음
.github/workflows/   push하면 자동 빌드·배포
```

시즌마다 폴더가 따로 있어서 지난 시즌 기록은 그대로 남는다.
사이트 주소 `/`는 항상 최신 시즌을 보여주고, `/25-26/`, `/26-27/`처럼 시즌별 주소가 따로 생긴다.

## 경기 후 할 일

```bash
# 1. 다음 라운드 파일 만들기 (라운드 번호와 날짜는 자동으로 채워짐)
python3 am6.py new futsal 2026-10-17
python3 am6.py new field 2026-10-24

# 2. 만들어진 seasons/25-26/games/20261017_futsal.yaml 을 채우고
#    맨 위의 draft: true 줄을 지운다 (지우기 전에는 사이트에 반영되지 않음)

# 3. 확인 후 올리기
python3 am6.py build          # public/index.html 을 브라우저로 열어 확인 (선택)
git add seasons && git commit -m "R33" && git push
```

push하고 1~2분 뒤에 사이트가 갱신된다.

### 외부 팀과 경기 (필드)

`opponent:`에 상대 팀 이름을 적고, 쿼터마다 우리 팀 하나만 적은 뒤 `opponent_goals:`에 그 쿼터 상대 득점을 적는다.
`opponent_goals`가 있어야 클린시트가 맞게 계산되고 사이트에 스코어가 나온다. 예시는 `seasons/25-26/games/20261017_field.yaml`.

```yaml
opponent: "상대팀이름"
win_team: "진우"       # 우리 팀 = 그날 감독 이름. 지면 상대팀 이름, 무승부면 null
quarters:
  1:
    진우: {GK: [...], DF: [...], MF: [...], FW: [...]}
    opponent_goals: 1
    goals: {박서룡: 1}
    assists: {}
```
PC가 없을 때는 GitHub 웹(모바일 포함)에서 `seasons/25-26/games/`에 파일을 바로 추가하거나 고쳐도 된다.

## 새 시즌 시작

```bash
python3 am6.py season 26-27 --period "2026.12 – 2027.11"
```

직전 시즌의 회원 명단과 가중치를 복사한다. 요약 탭 출석 패널(`features`)은 꺼진 채로 시작한다. `seasons/26-27/config.yaml`에서 회원과 가중치를 확인한 뒤 경기를 추가한다.

## 웹페이지 구성

- 요약: 최근 경기 결과, 시즌 숫자, 부문별 TOP 7 (파워랭킹, 출장, 풋살 득점, 필드 득점, 도움, 공격 포인트, 클린시트, 최다승, 쿼터 출전). 이름 옆 ▲▼는 최근 경기 직전 대비 순위 변동
- 출석 패널 (선택): 시즌 `config.yaml`의 `features`에서 켠 것만 요약 탭에 나온다
  - `absence`: 보고 싶은 얼굴. 3경기 이상 연속 결장한 정회원
  - `streak`: 연속 출석. 최근 경기까지 2경기 이상 연속 출석
  - `rank_preview`: 다음 경기에 나오면. 평소 경기당 포인트(시즌 포인트 ÷ 출석)를 더했을 때 오르는 예상 순위
- 파워랭킹: 회원 전체 표. 열 제목을 누르면 정렬. 포인트 계산 방식 설명 포함
- 경기 기록: 라운드별 결과, 쿼터 스코어, 득점·도움, 심판, 팀 명단
- 시너지: 최고·아쉬운 조합, 선수별 잘 맞는/덜 맞는 동료, 전체 매트릭스 (칸을 누르면 두 선수 기록 표시)
- 선수 검색: 이름이나 초성(ㅂㅊㅇ)으로 검색. 출석 현황, 포인트 구성, 경기 유형별·경기별 기록

## 계산 규칙

구글 시트 Summary_sheet 수식과 같은 규칙이다. R32 데이터로 회원 38명 전원의 숫자가 시트와 같은지 확인했다.

- 종합포인트 = 출석×10 + 유형별(승리·득점·도움·무실점 × 가중치) + 주심×2 + 부심×1
- 승리: 경기 유형별로 그 경기에서 이긴 팀이면 1
- 무실점: 실점 없이 끝난 쿼터에 뛴 선수 모두에게 쿼터마다 1
- 참여율 = 출장 경기 수 / 시즌 전체 경기 수
- 시너지: 같은 쿼터·같은 팀으로 뛴 정회원 두 명의 (승률 + 쿼터당 공격포인트 + 무실점률) / 3 을
  3쿼터 이상 조합과 1~2쿼터 조합 각각 안에서 1~5점으로 정규화 (예전 synergy_matrix.py와 결과 동일)
- 원본 기록과 다르게 집계해야 하면 `config.yaml`의 `adjustments`에 적는다
  (지금은 시트에서 김상범 8:8 무실점을 0으로 직접 고쳐 둔 것을 재현해 둠)

## 처음 한 번만: GitHub 설정

1. GitHub에서 새 저장소를 만든다 (예: `am6-stats`)
2. 이 폴더에서:
   ```bash
   git init -b main
   git add .
   git commit -m "AM6 기록 사이트"
   git remote add origin https://github.com/<아이디>/am6-stats.git
   git push -u origin main
   ```
3. 저장소 Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 바꾼다
4. Actions 탭에서 배포가 끝나면 `https://<아이디>.github.io/am6-stats/` 로 접속한다

무료 GitHub Pages는 저장소가 공개(public)여야 한다. 그러면 YAML 기록도 공개된다.
기록을 비공개로 두려면 저장소를 private으로 만들고 Cloudflare Pages(무료)에 연결한다.
설정은 Build command `pip install pyyaml && python am6.py build`, Output directory `public`이다.

## 기타 명령

```bash
python3 am6.py tsv seasons/25-26/games/20261010_futsal.yaml   # 예전처럼 시트에 붙여넣을 TSV 출력
python3 export_history.py "data/<시트파일>.xlsx" 25-26         # 시트에서 history.tsv 다시 뽑기 (1회용)
```

`generate_raw.py`는 `am6.py`가 내부에서 쓰므로 지우지 않는다.
예전 파일(`yaml/`, `output/`, `*.js`, `create_stats_sheet.py`)은 더 쓰지 않으니 정리해도 된다.
`synergy_matrix.py`도 시너지 탭으로 옮겼으니 더 쓰지 않아도 된다.
