# Subnautica AI

Subnautica의 PDA·함선 AI 대사를 사용하는 CESP v1.0 음성 팩입니다.
합의한 첫 표의 7개 이벤트를 각 1개 음원으로 구성했습니다.
자원 부족은 산소 경고, 오류는 화재 경고를 사용합니다.
대사 원문과 파일별 SHA-256은 `openpeon.json`에 있습니다.

## 구성

| 이벤트 | 대사 역할 | 파일 |
|---|---|---|
| `session.start` | 승선 인사 | `sounds/welcome_aboard.wav` |
| `task.acknowledge` | 엔진 시동 | `sounds/engine_powering_up.wav` |
| `task.complete` | 설계도 획득 | `sounds/blueprint_acquired.wav` |
| `task.error` | 화재 경고 | `sounds/fire_detected.wav` |
| `input.required` | 새 메시지 알림 | `sounds/new_message.wav` |
| `resource.limit` | 산소 경고 | `sounds/oxygen.wav` |
| `user.spam` | 정숙 운항 | `sounds/silent_running.wav` |

7개 모두 원본 그대로의 48 kHz / 16-bit PCM / stereo WAV입니다.
길이는 1.316~2.439초이며, 음원 전체 크기는 2,640,254 bytes입니다.
변환·증폭·무음 제거·음성 합성을 적용하지 않았습니다.
`preview.html`을 브라우저로 열면 별도 서버 없이 개별 음원을 재생할 수 있습니다.

## 검증 및 재현

Python 환경과 의존성은 uv로 관리합니다.

```sh
uv run --locked --script scripts/pack.py check
uv run --locked --script scripts/pack.py build
uv run --locked --script scripts/pack.py archive
```

- `check`: 포함된 공식 스키마, 매니페스트 매핑, SHA-256, CRC32, PCM 형식, 길이·크기 제한을 검증합니다. 의존성이 준비된 환경에서는 네트워크 없이 실행됩니다.
- `build`: 누락된 WAV만 `sources.json`의 고정 출처에서 복원합니다. 기존 파일이 체크섬과 다르면 덮어쓰지 않고 실패합니다.
- `archive`: 검증 후 `dist/subnautica_ai-1.0.0.zip`을 만듭니다. ZIP 루트에 매니페스트와 `sounds/`가 놓입니다.

복원 시 공개 오디오 ZIP에서 필요한 byte range만 받아 전체 아카이브를 다운로드하지 않습니다.
서버가 Range를 무시하거나 출처의 파일이 변경되면 실패합니다.
매니페스트와 실제 파일을 함께 보관하면 복원 작업 없이 사용할 수 있습니다.

## 로컬 설치

기본 공유 경로는 `~/.openpeon/packs/subnautica_ai/`입니다.
그 디렉터리에 ZIP을 풀면 루트에 `openpeon.json`과 `sounds/`가 있어야 합니다.
기존 설치가 있다면 덮어쓰기 전에 백업하십시오.
실제 플레이어가 다른 팩 경로를 사용하는 경우 해당 설정을 따르십시오.
이 작업에서는 기존 플레이어 설정이나 활성 팩을 변경하지 않았습니다.

## CESP와 런타임 지원

2026-11-05에 공식 upstream을 확인한 기준으로 CESP는 여전히 v1.0이며 총 9개 카테고리입니다.

| 구분 | 카테고리 |
|---|---|
| 핵심 6개 | `session.start`, `task.acknowledge`, `task.complete`, `task.error`, `input.required`, `resource.limit` |
| 선택 확장 3개 | `user.spam`, `session.end`, `task.progress` |

팩은 이 중 7개만 제공하며 `session.end`, `task.progress`는 포함하지 않습니다.
최신 peon-ping v2.37.0 문서상 두 이벤트는 매니페스트에서 지원하지만 내장 훅이 발생시키지는 않습니다.
실제 이벤트 발생 여부는 어댑터별로 다릅니다. `task.acknowledge`는 기본 설정에서 비활성일 수 있습니다.

- [고정 버전의 공식 CESP 스펙](https://github.com/PeonPing/openpeon/blob/b0727d5abefc882982c4c7349bd1a8c45b1b73b1/spec/cesp-v1.md)
- [검증에 사용한 공식 스키마](https://github.com/PeonPing/openpeon/blob/b0727d5abefc882982c4c7349bd1a8c45b1b73b1/spec/openpeon.schema.json)
- [peon-ping 지원 범위](https://github.com/PeonPing/peon-ping/blob/3008c0fff4b9a658378644d9223975acd0e7cc6f/README.md#L330)

## 출처와 권리

대사 선정은 [Subnautica Wiki의 Dialogue 목록](https://subnautica.fandom.com/wiki/Dialogue_%28Subnautica%29)을 기준으로 했습니다.
위키 CDN의 자동 다운로드가 차단되어, 실제 WAV는 [공개 오디오 아카이브 v83031](https://github.com/rachit9876/subnautica-all-audio/releases/tag/v83031)에서 확보했습니다.
위키의 OGG와 바이트가 동일하다는 의미는 아닙니다. 원본 멤버 이름·출처·체크섬은 `sources.json`에 기록했습니다.
음성 인식으로 대사 대응을 점검했으며, 라디오 알림의 첫 호칭은 음성 인식에서 확인되지 않았습니다.
청감 검수는 `preview.html`에서 할 수 있습니다.

게임 음원의 권리는 Unknown Worlds Entertainment 및 해당 권리자에게 있습니다.
매니페스트의 `LicenseRef-Subnautica-Audio`는 이 권리 고지를 가리키며, 게임 음원에 대한 재배포 허가를 부여하지 않습니다.
직접 작성한 메타데이터·문서·스크립트와 외부 음원의 권리를 구분합니다. 자세한 내용은 `LICENSE`를 참고하십시오.
동봉한 공식 스키마는 원본 MIT 라이선스(`schema/LICENSE`)를 따릅니다.
