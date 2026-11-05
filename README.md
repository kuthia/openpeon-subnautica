# Subnautica PDA

원작 Subnautica의 PDA 보이스로 통일한 CESP v1.0 음성 팩입니다.
v1.1.0에서 기존 혼합 구성의 5개 음원을 PDA 대사로 교체했습니다.
자원 부족의 산소 경고와 작업 완료의 설계도 획득 음원은 원본 바이트를 유지했습니다.
팩 ID는 기존 설치에서 계속 사용할 수 있도록 `subnautica_ai`를 유지합니다.
개인 사용을 위한 공개 저장소이며 OpenPeon 레지스트리 제출은 보류 중입니다.

## 구성

| 이벤트 | 대사 요지 | 길이 | 파일 |
|---|---|---:|---|
| `session.start` | 짧은 행운 인사 | 0.80초 | `sounds/good_luck.wav` |
| `task.acknowledge` | 새로운 PDA 데이터 통합 | 2.12초 | `sounds/integrating_data.wav` |
| `task.complete` | 설계도 획득 | 1.78초 | `sounds/blueprint_acquired.wav` |
| `task.error` | 현재 위치에서 빌드 불가 | 1.20초 | `sounds/cannot_build_here.wav` |
| `input.required` | 자가진단 수행 권고 | 2.33초 | `sounds/self_scan_advised.wav` |
| `resource.limit` | 산소 경고 | 1.32초 | `sounds/oxygen.wav` |
| `user.spam` | 앉아서 명상하도록 권유 | 2.60초 | `sounds/take_a_seat.wav` |

7개 모두 원작 PDA 대사이며, 게임 오디오 아카이브의 `Player[0]` 뱅크에서 가져왔습니다.
음성 분류는 실제 게임 내 PDA 대사라는 출처와 음원 전사 점검을 근거로 합니다.
보관 위치만으로 동일 보이스라고 판단하지 않으며, 차량·기지·라디오 AI 대사는 제외했습니다.
대사 원문과 파일별 SHA-256은 `openpeon.json`에 있습니다.

출력은 모두 48 kHz / 16-bit PCM / stereo WAV입니다.
시작·오류·입력 요청·연속 입력의 4개 파일은 원본의 완결문장을 프레임 단위로 잘랐습니다.
선택된 PCM 프레임은 그대로 보존하며, 원본과 출력의 체크섬을 각각 기록했습니다.
잘라낸 4개 문장은 무음 경계와 음성 인식으로 앞뒤 문장 혼입·단어 누락을 점검했습니다.
음원 전체 크기는 2,331,950 bytes입니다.
`preview.html`을 브라우저로 열면 별도 서버 없이 개별 음원을 재생할 수 있습니다.

## 검증 및 재현

Python 환경과 의존성은 uv로 관리합니다.

```sh
uv run --locked --script scripts/pack.py check
uv run --locked --script scripts/pack.py build
uv run --locked --script scripts/pack.py archive
```

- `check`: 포함된 공식 스키마, 매니페스트 매핑, 보이스 분류, SHA-256, CRC32, PCM 형식, 길이·크기 제한을 검증합니다. 의존성이 준비된 환경에서는 네트워크 없이 실행됩니다.
- `build`: 누락된 WAV만 `sources.json`의 고정 출처에서 복원하고 지정된 프레임 구간을 재현합니다. 기존 파일의 체크섬이 다르면 덮어쓰지 않고 실패합니다.
- `archive`: 검증 후 `dist/subnautica_ai-1.1.0.zip`을 만듭니다. ZIP 루트에 매니페스트와 `sounds/`가 놓입니다.

복원 시 공개 오디오 ZIP에서 필요한 byte range만 받아 전체 아카이브를 다운로드하지 않습니다.
서버가 Range를 무시하거나 출처의 파일이 변경되면 실패합니다.
`source_size/source_crc32/source_sha256`는 원본, `size/crc32/sha256`는 출력에 해당합니다.
`trim.start_frame`은 포함, `trim.end_frame`은 제외하는 원본 48 kHz 프레임 위치입니다.
매니페스트와 실제 파일을 함께 보관하면 복원 작업 없이 사용할 수 있습니다.

## 로컬 설치

레지스트리에 없어도 peon-ping의 `peon packs install-local`로 이 저장소의 로컬 디렉터리를 설치할 수 있습니다.
설치 후 `peon packs use`에서 팩 ID `subnautica_ai`를 선택합니다.
이 명령은 폴더를 복사하므로, 업데이트한 음원을 반영하려면 다시 설치해야 합니다.
이미 설치된 팩을 교체할 때는 명령의 `--force` 옵션을 사용합니다.

수동 설치의 기본 공유 경로는 `~/.openpeon/packs/subnautica_ai/`입니다.
ZIP을 풀면 그 디렉터리 루트에 `openpeon.json`과 `sounds/`가 있어야 합니다.
실제 플레이어가 다른 팩 경로를 사용하는 경우 해당 설정을 따르십시오.

## CESP와 런타임 지원

2026-11-05에 공식 upstream을 확인한 기준으로 CESP는 v1.0이며 총 9개 카테고리입니다.

| 구분 | 카테고리 |
|---|---|
| 핵심 6개 | `session.start`, `task.acknowledge`, `task.complete`, `task.error`, `input.required`, `resource.limit` |
| 선택 확장 3개 | `user.spam`, `session.end`, `task.progress` |

팩은 이 중 7개를 제공합니다.
peon-ping 문서상 `session.end`, `task.progress`는 매니페스트에서 지원하지만 내장 훅이 발생시키지는 않습니다.
실제 이벤트 발생 여부는 어댑터별로 다르며, `task.acknowledge`는 기본 설정에서 비활성일 수 있습니다.

- [공식 CESP 스펙](https://github.com/PeonPing/openpeon/blob/b0727d5abefc882982c4c7349bd1a8c45b1b73b1/spec/cesp-v1.md)
- [검증에 사용한 공식 스키마](https://github.com/PeonPing/openpeon/blob/b0727d5abefc882982c4c7349bd1a8c45b1b73b1/spec/openpeon.schema.json)
- [peon-ping 명령과 지원 범위](https://github.com/PeonPing/peon-ping#quick-controls)

## 출처와 권리

대사 선정은 [Subnautica Wiki의 Dialogue 목록](https://subnautica.fandom.com/wiki/Dialogue_%28Subnautica%29)과 실제 PDA 음원을 기준으로 했습니다.
데이터 통합 알림은 [Nautilus의 PDAHandler 문서](https://subnauticamodding.github.io/Nautilus/api/Nautilus.Handlers.PDAHandler.html)에서도 PDA 이벤트로 확인할 수 있습니다.
실제 WAV는 [공개 오디오 아카이브 v83031](https://github.com/rachit9876/subnautica-all-audio/releases/tag/v83031)에서 확보했습니다.
원본 멤버 이름·출처·체크섬·편집 구간은 `sources.json`에 기록했습니다.
위키 전사와 아카이브의 문구가 다를 수 있어, 실제 사용한 음원의 전사를 매니페스트에 반영했습니다.

게임 음원의 권리는 Unknown Worlds Entertainment 및 해당 권리자에게 있습니다.
매니페스트의 `LicenseRef-Subnautica-Audio`는 이 권리 고지를 가리키며, 게임 음원에 대한 재배포 허가를 부여하지 않습니다.
직접 작성한 메타데이터·문서·스크립트와 외부 음원의 권리를 구분합니다. 자세한 내용은 `LICENSE`를 참고하십시오.
동봉한 공식 스키마는 원본 MIT 라이선스(`schema/LICENSE`)를 따릅니다.
