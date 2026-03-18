# Slay_the_spire_map_autodrawer

이미지를 자동으로 트레이싱하는 마우스 매크로 프로그램입니다.  
Canny 엣지 검출 + 획(stroke) 기반 드래그로 그림판, 브라우저 캔버스 등 어디서든 그림을 자동으로 그립니다.

그림판 기준으로는 점선으로 그려지는 형식상의 문제가 있어
펜 굵기가 굵은 상황에서 쓰면 좋습니다.
특히, Slay the Spire 2 의 맵에서 그림을 그리는 기능에서 잘 작동함을 확인했습니다.
---

## 기능

- 로컬 이미지 파일 또는 **URL**로 이미지 입력
- 드래그로 그릴 영역 직접 지정
- Canny 엣지 민감도 슬라이더 조절
- 획(stroke) 단위 드래그 방식으로 빠른 드로잉
- ESC 키로 즉시 중단
- 그리기 완료 후 임시 파일 자동 삭제

---

## 실행 방법

### 방법 1 — EXE (Python 불필요)

[Releases](../../releases) 페이지에서 `AutoDrawer.exe` 다운로드 후 실행

### 방법 2 — Python으로 직접 실행

**요구사항**
- Python 3.9 이상

**의존성 설치**
```bash
pip install opencv-python numpy pyautogui keyboard
```

> thinning(세선화) 품질 향상을 원한다면 (선택사항):
> ```bash
> pip install opencv-contrib-python
> ```
> `opencv-contrib-python`을 설치할 경우 `opencv-python`은 제거해야 합니다:
> ```bash
> pip uninstall opencv-python
> pip install opencv-contrib-python
> ```

**실행**
```bash
python new.py
```

---

## 사용 방법

1. 프로그램 실행
2. 이미지 경로 입력 또는 파일 선택 (URL도 가능)
3. **드래그로 영역 선택** 버튼 클릭 → 그릴 위치를 드래그로 지정
4. 엣지 민감도, 속도 설정 조절
5. 그림판 등 대상 앱을 열고 브러시 선택
6. **트레이싱 시작** 클릭 → 카운트다운 후 자동으로 그림 그림
7. 중단하려면 **ESC**

---

## 설정 설명

| 설정 | 설명 |
|------|------|
| Threshold 1 / 2 | Canny 엣지 민감도. 낮을수록 선이 많아짐 |
| 시작 대기(초) | 매크로 시작 전 준비 시간 |
| 획 단순화(epsilon) | 클수록 빠르지만 덜 정밀. 0이면 완전 정밀 |
| 점간 딜레이 | 획 내 점 사이 딜레이. 앱이 느리면 올릴 것 |
| 획간 딜레이 | 획과 획 사이 딜레이. 끊김 방지 |

---

## 주의사항

- Windows 전용입니다
- 트레이싱 중 마우스를 직접 움직이면 오작동할 수 있습니다
- 화면 배율이 100%가 아닌 경우 좌표가 어긋날 수 있습니다

---

## 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| opencv-python | ≥ 4.5 | 이미지 처리, 엣지 검출 |
| numpy | ≥ 1.21 | 배열 연산 |
| pyautogui | ≥ 0.9 | 마우스 제어 (Failsafe용) |
| keyboard | ≥ 0.13 | ESC 단축키 감지 |

---

## 빌드 (EXE 생성)

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole new.py
```

`dist/new.exe` 생성됨
