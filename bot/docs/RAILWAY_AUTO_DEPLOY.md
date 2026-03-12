# Railway 자동 배포가 안 될 때

## 1. 자동 배포 켜기

1. **Railway 대시보드** → 프로젝트 선택 → **bot** 서비스 클릭
2. **Settings** 탭 이동
3. **Source** 섹션에서:
   - **Connect Repo** 가 되어 있는지 확인 (GitHub 저장소 연결)
   - **Branch**: `main` (또는 푸시하는 브랜치) 로 되어 있는지 확인
   - **Auto Deploy**: **On** 인지 확인 (푸시 시 자동 배포)

또는:

- **Deployments** 탭 → 우측 상단 또는 설정에서 **Deploy on push** / **Auto Deploy** 옵션이 켜져 있는지 확인

## 2. 수동 배포로 당장 올리기

자동 배포를 나중에 맞추고, 지금은 수동으로 배포하려면:

1. **Railway** → **bot** 서비스 → **Deployments** 탭
2. **Deploy** 또는 **Redeploy** 버튼 클릭  
   (또는 최신 배포 행의 **⋯** 메뉴 → **Redeploy**)
3. GitHub **main** 최신 커밋 기준으로 다시 빌드·배포됨

## 3. 모노레포(bot + automation)인 경우

저장소 루트가 `c:\my bot` 이고 안에 `bot/`, `automation/` 이 있으면:

- bot 서비스의 **Root Directory** (또는 **Watch Paths**)가 **bot** 으로 설정돼 있는지 확인
- 그래야 `bot/` 폴더만 변경해도 bot 서비스만 배포됨

## 4. 확인

- **Deployments** 탭에서 최신 배포가 **Success** 인지
- **로그**에서 `기동 시 env: CHANNEL_ID=...` 로 봇이 기동했는지 확인
