"use client";

import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  startTransition,
  useState,
} from "react";

export const supportedLocales = ["en", "ko"] as const;
export type Locale = (typeof supportedLocales)[number];

const localeStorageKey = "tripweave.locale";

const messages = {
  en: {
    "language.label": "Language",
    "landing.signIn": "Sign in",
    "landing.eyebrow": "One journey, woven together",
    "landing.title":
      "Turn everyone's travel photos into one story worth revisiting.",
    "landing.description":
      "TripWeave brings scattered camera rolls into a shared map and timeline, so the moments of a trip can live together in one place.",
    "landing.startTrip": "Start a trip",
    "landing.exploreExample": "Explore the example",
    "landing.privacy":
      "Your original photos stay private. Shared stories use selected, privacy-conscious derivatives.",
    "landing.exampleEyebrow": "See a real TripWeave story",
    "landing.exampleTitle": "An example trip, ready to explore",
    "landing.openStory": "Open full story",
    "landing.exampleFrameTitle": "Example TripWeave story",
    "landing.exampleCaption":
      "Browse the map, timeline, and shared moments before creating a trip of your own.",
    "auth.createOwnerAccount": "Create owner account",
    "auth.signIn": "Sign in",
    "auth.displayName": "Display name",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.working": "Working...",
    "auth.register": "Register",
    "auth.alreadyHaveAccount": "Already have an account?",
    "auth.createAccount": "Create an owner account",
    "auth.back": "Back to TripWeave",
    "common.cancel": "Cancel",
    "common.logout": "Logout",
    "onboarding.backToTrips": "Back to my trips",
    "onboarding.eyebrow": "Your shared travel story starts here",
    "onboarding.title": "Turn scattered travel photos into one shared story.",
    "onboarding.description":
      "Create a trip, invite the people who were there, and weave everyone's moments into a journey you can revisit.",
    "onboarding.stepsLabel": "How TripWeave works",
    "onboarding.step1Title": "Create a trip",
    "onboarding.step1Description":
      "Give the journey a home before the photos arrive.",
    "onboarding.step2Title": "Add photos together",
    "onboarding.step2Description":
      "Invite fellow travelers to contribute their moments.",
    "onboarding.step3Title": "Revisit the story",
    "onboarding.step3Description":
      "See the trip take shape as a map and timeline.",
    "onboarding.locationTitle": "Turn on photo location",
    "onboarding.locationDescription":
      "Enable Location in your camera settings. GPS helps TripWeave place photos on the map and build your route. Photos without GPS can still be included, but may not appear on the map.",
    "onboarding.exploreExample": "Explore an example trip",
    "onboarding.stepOne": "Step 1",
    "onboarding.createTitle": "Create your first trip",
    "onboarding.createDescription":
      "Give it a name and add any details you already know.",
    "trip.creating": "Creating trip...",
    "trip.create": "Create trip",
    "trip.createNew": "Create a new trip",
    "trip.createDescription":
      "Start with the details you know. You can add photos next.",
    "trip.title": "Title",
    "trip.description": "Description",
    "trip.optional": "Optional",
    "trip.startDate": "Start date",
    "trip.endDate": "End date",
    "trip.dayCutoff": "New day starts at",
    "trip.dayCutoffDescription":
      "Photos before this hour are grouped with the previous day.",
    "workspace.tripNavigation": "Trip navigation",
    "workspace.sections": "Workspace sections",
    "workspace.map": "Map",
    "workspace.timeline": "Timeline",
    "workspace.slideshow": "Play slideshow",
    "workspace.moreOptions": "More options",
    "workspace.currentTrip": "Current trip",
    "workspace.currentTripActions": "Current trip actions",
    "workspace.appActions": "App-wide actions",
    "workspace.shareTrip": "Share trip",
    "workspace.createNewTrip": "Create a new trip",
    "workspace.settings": "Settings",
    "workspace.trips": "Trips",
    "workspace.story": "Story",
    "workspace.tripMap": "Trip map",
    "workspace.photos": "Photos",
    "workspace.savedStories": "Saved stories",
    "workspace.manageTrip": "Manage trip",
    "workspace.review": "Review",
    "workspace.noTrips": "No trips yet.",
    "workspace.guide": "How TripWeave works",
    "workspace.viewOnboarding": "View onboarding",
    "workspace.tripCount": "{count} trip{suffix}",
    "upload.addPhotos": "Add photos",
    "upload.description": "Upload JPEG or HEIC photos to this trip",
    "upload.fileTypes": "JPEG and HEIC",
    "upload.locationTitle": "Turn on photo location",
    "upload.locationDescription":
      "Enable Location in your camera settings. GPS helps TripWeave place photos on the map and build your route. Photos without GPS can still be included, but may not appear on the map.",
    "upload.selectTrip": "Select a trip before uploading photos.",
    "upload.status": "Upload status",
    "upload.uploading": "Uploading {count}",
    "upload.needsAttention": "Uploads need attention",
    "upload.failed": "Failed {count}",
    "upload.complete": "{percent}% complete",
    "upload.progress": "Upload progress",
    "upload.unknownType": "unknown type",
    "upload.cancel": "Cancel",
    "upload.retry": "Retry",
    "collaboration.inviteTravelers": "Invite travelers",
    "collaboration.inviteDescription": "Invite friends to add photos",
    "collaboration.memberCount": "{count} member{suffix}",
    "collaboration.createInvite": "Create shared invite link",
    "collaboration.noInvitations": "No invitations yet.",
    "collaboration.joined": "joined",
    "collaboration.revoke": "Revoke",
    "collaboration.copyLink": "Copy link",
    "collaboration.invitationQr": "Invitation QR code",
    "collaboration.noMembers": "No members yet.",
    "collaboration.guest": "guest",
    "collaboration.removed": "removed",
    "collaboration.remove": "Remove",
    "publication.title": "Publish story",
    "publication.description": "Share a read-only story with anyone",
    "publication.activeLinks": "{count} active link{suffix}",
    "publication.publish": "Publish",
    "publication.unpublish": "Unpublish",
    "publication.latest": "Latest published story",
    "publication.copyLink": "Copy link",
    "publication.noData": "No publication data loaded.",
    "publication.versions": "Published versions",
    "publication.latestStory": "Latest Story",
    "publication.latestDescription":
      "Always opens the newest published version",
    "publication.copyLatest": "Copy latest link",
    "publication.noVersions": "No versions yet.",
    "publication.version": "Version {number}",
    "publication.publishing": "Publishing",
    "publication.copyVersion": "Copy version link",
    "settings.description": "Edit trip info or update its story",
    "settings.updateStory": "Update story",
    "settings.updateDescription":
      "Rebuild the map and timeline from your latest photos.",
    "settings.save": "Save changes",
    "settings.deleteTrip": "Delete trip",
    "settings.selectTrip": "Select a trip to edit its settings.",
    "review.description": "Resolve questions in your trip",
    "review.issueCount": "{count} issue{suffix}",
    "appSettings.description": "Account and workspace preferences",
    "appSettings.signedIn": "Signed in",
    "publicStory.eyebrow": "Published story",
    "publicStory.loading": "Loading story",
    "publicStory.unavailable": "Story unavailable",
    "publicStory.notAvailable": "This story is not available.",
    "publicStory.myTrips": "My trips",
    "publicStory.home": "TripWeave home",
    "publicStory.title": "TripWeave story",
    "publicStory.defaultTitle": "Trip story",
    "publicStory.version": "Published version {number}",
    "publicStory.publishedBy": "Published by {name}",
    "publicStory.view": "Story view",
    "publicStory.slideshow": "Slideshow",
    "publicStory.save": "Save",
    "publicStory.saved": "Saved",
    "publicStory.removeSaved": "Remove from saved stories",
    "publicStory.saveStory": "Save story",
    "invite.eyebrow": "TripWeave invitation",
    "invite.loading": "Loading invitation",
    "invite.description":
      "Sign in or create an account to join this trip as a {role}.",
    "invite.signedInAs": "Signed in as {name}.",
    "invite.join": "Join trip",
    "invite.accountMode": "Invitation account mode",
    "invite.login": "Log in",
    "invite.createAccount": "Create account",
    "invite.createAndJoin": "Create account and join",
    "invite.loginAndJoin": "Log in and join",
    "contributor.loading": "Loading contribution page",
    "contributor.eyebrow": "Contributor upload",
    "contributor.welcome": "Welcome, {name}",
    "contributor.unavailable": "Contribution unavailable",
    "contributor.addImages": "Add JPEG or HEIC images",
    "contributor.ownUploads": "Only your uploads are shown here.",
    "contributor.uploadGrantUnavailable": "Upload permission is unavailable",
    "contributor.tooManyFiles":
      "This trip can hold {max} photos. Remove or cancel an upload before adding more.",
    "media.noProcessed": "No processed media yet.",
    "media.openPhoto": "Open {name}",
    "media.photo": "photo",
    "media.untitled": "Untitled image",
    "media.stack": "stack of {count}",
    "media.representative": "representative",
    "media.visibility": "Visibility",
    "media.visibilityLabel": "Photo visibility",
    "media.memberOnly": "Member only",
    "media.public": "Public",
    "media.visibilityHelp": "Photo visibility help",
    "media.whoCanSee": "Who can see this photo?",
    "media.memberOnlyDescription":
      "Member only keeps it inside this trip. Public lets it appear in a published story.",
    "media.sanitizedDescription":
      "Published stories use a sanitized derivative, never the original photo.",
    "media.closeVisibilityHelp": "Close photo visibility help",
    "media.captured": "Captured",
    "media.gps": "GPS",
    "media.present": "Present",
    "media.notFound": "Not found",
    "media.update": "Update",
    "media.dimensions": "Dimensions",
    "media.unknown": "Unknown",
    "media.retryProcessing": "Retry processing",
    "media.deletePhoto": "Delete photo",
    "media.adjustLocation": "Adjust photo location",
    "media.locationEyebrow": "Photo location",
    "media.photoFallback": "Photo",
    "media.locationInstruction":
      "Move the map until the desired place is under the center pin.",
    "media.selectedLocation": "Selected location",
    "media.currentLocation": "Blue dot: current photo location",
    "media.noLocation": "No location saved for this photo yet.",
    "media.saving": "Saving…",
    "media.useLocation": "Use this location",
    "media.similarTitle": "Similar photo stacks",
    "media.similarDescription":
      "Duplicate and near-duplicate versions stay preserved.",
    "media.versions": "{count} versions",
    "media.confidence": "confidence",
    "media.technical": "technical",
    "media.similarity": "similarity",
    "media.useRepresentative": "Use as representative",
    "review.noRun": "No reconstruction run yet.",
    "review.days": "days",
    "review.stops": "stops",
    "review.items": "review items",
    "review.inbox": "Review inbox",
    "review.openIssues": "{count} open issue{suffix}",
    "review.clear": "clear",
    "review.undo": "Undo latest edit",
    "review.confidence": "confidence",
    "review.offset": "Offset",
    "review.support": "Support",
    "review.dispersion": "Dispersion",
    "review.threshold": "Threshold",
    "review.diameter": "Diameter",
    "review.acceptOffset": "Accept offset",
    "review.resolve": "Resolve",
    "review.dismiss": "Dismiss",
    "review.skip": "Skip",
    "review.noOpen": "No open review items.",
    "review.noMedia": "No usable media has been grouped yet.",
    "review.stop": "Stop {position}",
    "review.to": "to",
    "review.mediaCount": "{count} media",
    "review.contributorCount": "{count} contributors",
    "review.moment": "Moment {position}",
    "admin.dashboard": "Operations dashboard",
    "admin.loading": "Loading operations dashboard",
    "admin.accessRequired": "Operator access required",
    "admin.accessDescription":
      "Sign in with an account configured for operator access.",
    "admin.overview": "Operations overview",
    "admin.overviewDescription": "Usage, audience activity, and quota controls",
    "admin.last30Days": "Last 30 days",
    "admin.usageSummary": "Usage summary",
    "admin.users": "Users",
    "admin.todaySignedIn": "Signed-in today",
    "admin.todayViews": "Story views today",
    "admin.activity": "Daily activity",
    "admin.activityDescription":
      "New accounts, content creation, and public story reach.",
    "admin.date": "Date",
    "admin.newUsers": "New users",
    "admin.newTrips": "New trips",
    "admin.storyViews": "Story views",
    "admin.tripsViewed": "Trips viewed",
    "admin.distributions": "Usage distributions",
    "admin.distributionsDescription":
      "How usage is spread across users and trips.",
    "admin.userTrips": "User trips",
    "admin.userPhotos": "User photos",
    "admin.photosPerTrip": "Photos per trip",
    "admin.average": "Average {value}",
    "admin.tiers": "Tier management",
    "admin.tiersDescription":
      "Review plan limits and update individual accounts.",
    "admin.unlimited": "unlimited",
    "admin.monthly": "monthly",
    "admin.userManagement": "User management",
    "admin.userManagementDescription":
      "Find an account, review its usage, and explicitly save tier changes.",
    "admin.findUser": "Find a user",
    "admin.findUserDescription":
      "Search by email to review usage and change a tier.",
    "admin.searchEmail": "Search by email",
    "admin.searchUsers": "Search users",
    "admin.user": "User",
    "admin.usage": "Usage",
    "admin.tier": "Tier",
    "admin.tierFor": "Tier for {email}",
    "admin.updating": "Updating...",
    "admin.updateTier": "Update tier",
    "admin.createTier": "Create tier",
    "admin.internalId": "Internal ID (slug)",
    "admin.internalIdHint":
      "Stable machine-readable identifier. Use lowercase letters, numbers, and hyphens.",
    "admin.displayName": "Display name",
    "admin.maxTrips": "max trips (blank = unlimited)",
    "admin.maxPhotos": "max photos (blank = unlimited)",
    "admin.monthlyBytes": "monthly upload bytes",
    "story.loading": "Loading...",
    "story.empty":
      "Refresh the story after adding photos to build the map and timeline.",
    "story.selectedDayControls": "Selected day controls",
    "story.allDays": "All days",
    "story.browsePhotos": "Browse {date} photos",
    "story.photos": "photos",
    "story.selectedArea": "Selected area",
    "story.selectedStop": "Selected stop",
    "story.selectedDay": "Selected day",
    "story.mapNote": "Map note",
    "story.noStop": "No stop selected",
    "story.stopNote": "Stop note",
    "story.dayNote": "Day note",
    "story.timeline": "Timeline",
    "story.timelineDescription":
      "Follow the route through days, stops, and photo moments.",
    "story.follow": "Follow",
    "story.play": "Play",
    "story.browseAllPhotos": "Browse photos",
    "story.controls": "Story controls",
    "story.wholeTrip": "Whole trip",
    "story.days": "Story days",
    "story.all": "All",
    "story.viewMode": "View mode",
    "story.traveler": "Traveler",
    "story.everyone": "Everyone",
    "story.tripPhotos": "Trip photos",
    "story.groupedPhotos": "{count} photos grouped by stop",
    "story.browseDayPhotos": "Browse day photos",
    "story.chronologicalTimeline": "Chronological timeline",
    "story.timelineDays": "Timeline days",
  },
  ko: {
    "language.label": "언어",
    "landing.signIn": "로그인",
    "landing.eyebrow": "하나의 여행, 함께 엮어가요",
    "landing.title":
      "모두의 여행 사진을 다시 보고 싶은 하나의 이야기로 만들어 보세요.",
    "landing.description":
      "TripWeave는 흩어진 카메라 롤을 하나의 지도와 타임라인으로 엮어 여행의 순간을 한곳에 담습니다.",
    "landing.startTrip": "여행 시작하기",
    "landing.exploreExample": "예시 둘러보기",
    "landing.privacy":
      "원본 사진은 비공개로 유지됩니다. 공유되는 이야기는 개인정보를 고려해 선택한 파생 이미지로 구성됩니다.",
    "landing.exampleEyebrow": "실제 TripWeave 이야기 살펴보기",
    "landing.exampleTitle": "바로 둘러볼 수 있는 예시 여행",
    "landing.openStory": "전체 이야기 열기",
    "landing.exampleFrameTitle": "TripWeave 예시 여행 이야기",
    "landing.exampleCaption":
      "나만의 여행을 만들기 전에 지도, 타임라인, 함께한 순간을 둘러보세요.",
    "auth.createOwnerAccount": "소유자 계정 만들기",
    "auth.signIn": "로그인",
    "auth.displayName": "표시 이름",
    "auth.email": "이메일",
    "auth.password": "비밀번호",
    "auth.working": "처리 중...",
    "auth.register": "가입하기",
    "auth.alreadyHaveAccount": "이미 계정이 있으신가요?",
    "auth.createAccount": "소유자 계정 만들기",
    "auth.back": "TripWeave로 돌아가기",
    "common.cancel": "취소",
    "common.logout": "로그아웃",
    "onboarding.backToTrips": "내 여행으로 돌아가기",
    "onboarding.eyebrow": "함께한 여행 이야기가 여기서 시작됩니다",
    "onboarding.title": "흩어진 여행 사진을 하나의 이야기로 만들어 보세요.",
    "onboarding.description":
      "여행을 만들고 함께한 사람을 초대해, 모두의 순간을 다시 찾아볼 수 있는 여정으로 엮어 보세요.",
    "onboarding.stepsLabel": "TripWeave 이용 방법",
    "onboarding.step1Title": "여행 만들기",
    "onboarding.step1Description":
      "사진이 도착하기 전에 여행을 담을 공간을 만드세요.",
    "onboarding.step2Title": "함께 사진 추가하기",
    "onboarding.step2Description":
      "함께 여행한 사람을 초대해 각자의 순간을 더하세요.",
    "onboarding.step3Title": "이야기 다시 보기",
    "onboarding.step3Description":
      "지도와 타임라인으로 완성되는 여행을 살펴보세요.",
    "onboarding.locationTitle": "사진 위치 정보 켜기",
    "onboarding.locationDescription":
      "카메라 설정에서 위치 정보를 켜세요. GPS는 TripWeave가 사진을 지도에 표시하고 이동 경로를 만드는 데 도움이 됩니다. GPS가 없는 사진도 추가할 수 있지만 지도에는 표시되지 않을 수 있습니다.",
    "onboarding.exploreExample": "예시 여행 둘러보기",
    "onboarding.stepOne": "1단계",
    "onboarding.createTitle": "첫 여행 만들기",
    "onboarding.createDescription":
      "여행 이름을 정하고 알고 있는 정보를 추가하세요.",
    "trip.creating": "여행 만드는 중...",
    "trip.create": "여행 만들기",
    "trip.createNew": "새 여행 만들기",
    "trip.createDescription":
      "알고 있는 정보부터 입력하세요. 사진은 다음에 추가할 수 있습니다.",
    "trip.title": "제목",
    "trip.description": "설명",
    "trip.optional": "선택 사항",
    "trip.startDate": "시작일",
    "trip.endDate": "종료일",
    "trip.dayCutoff": "하루가 시작되는 시각",
    "trip.dayCutoffDescription": "이 시각 이전의 사진은 전날에 포함됩니다.",
    "workspace.tripNavigation": "여행 탐색",
    "workspace.sections": "작업 공간 섹션",
    "workspace.map": "지도",
    "workspace.timeline": "타임라인",
    "workspace.slideshow": "슬라이드쇼 재생",
    "workspace.moreOptions": "더보기",
    "workspace.currentTrip": "현재 여행",
    "workspace.currentTripActions": "현재 여행 작업",
    "workspace.appActions": "앱 전체 작업",
    "workspace.shareTrip": "여행 공유",
    "workspace.createNewTrip": "새 여행 만들기",
    "workspace.settings": "설정",
    "workspace.trips": "여행",
    "workspace.story": "이야기",
    "workspace.tripMap": "여행 지도",
    "workspace.photos": "사진",
    "workspace.savedStories": "저장한 이야기",
    "workspace.manageTrip": "여행 관리",
    "workspace.review": "검토",
    "workspace.noTrips": "아직 여행이 없습니다.",
    "workspace.guide": "TripWeave 이용 방법",
    "workspace.viewOnboarding": "온보딩 보기",
    "workspace.tripCount": "여행 {count}개",
    "upload.addPhotos": "사진 추가",
    "upload.description": "이 여행에 JPEG 또는 HEIC 사진을 업로드하세요",
    "upload.fileTypes": "JPEG 및 HEIC",
    "upload.locationTitle": "사진 위치 정보 켜기",
    "upload.locationDescription":
      "카메라 설정에서 위치 정보를 켜세요. GPS는 TripWeave가 사진을 지도에 표시하고 이동 경로를 만드는 데 도움이 됩니다. GPS가 없는 사진도 추가할 수 있지만 지도에는 표시되지 않을 수 있습니다.",
    "upload.selectTrip": "사진을 업로드할 여행을 선택하세요.",
    "upload.status": "업로드 상태",
    "upload.uploading": "{count}개 업로드 중",
    "upload.needsAttention": "업로드 확인 필요",
    "upload.failed": "실패 {count}개",
    "upload.complete": "{percent}% 완료",
    "upload.progress": "업로드 진행률",
    "upload.unknownType": "알 수 없는 파일 형식",
    "upload.cancel": "취소",
    "upload.retry": "다시 시도",
    "collaboration.inviteTravelers": "여행자 초대",
    "collaboration.inviteDescription": "친구를 초대해 사진을 추가하세요",
    "collaboration.memberCount": "구성원 {count}명",
    "collaboration.createInvite": "공유 초대 링크 만들기",
    "collaboration.noInvitations": "아직 초대가 없습니다.",
    "collaboration.joined": "참여함",
    "collaboration.revoke": "해제",
    "collaboration.copyLink": "링크 복사",
    "collaboration.invitationQr": "초대 QR 코드",
    "collaboration.noMembers": "아직 구성원이 없습니다.",
    "collaboration.guest": "게스트",
    "collaboration.removed": "제거됨",
    "collaboration.remove": "제거",
    "publication.title": "이야기 공개",
    "publication.description":
      "누구나 볼 수 있는 읽기 전용 이야기를 공유하세요",
    "publication.activeLinks": "활성 링크 {count}개",
    "publication.publish": "공개",
    "publication.unpublish": "공개 취소",
    "publication.latest": "가장 최근 공개된 이야기",
    "publication.copyLink": "링크 복사",
    "publication.noData": "불러온 공개 정보가 없습니다.",
    "publication.versions": "공개 버전",
    "publication.latestStory": "최신 이야기",
    "publication.latestDescription": "항상 가장 최신 공개 버전을 엽니다",
    "publication.copyLatest": "최신 링크 복사",
    "publication.noVersions": "아직 공개된 버전이 없습니다.",
    "publication.version": "버전 {number}",
    "publication.publishing": "공개 중",
    "publication.copyVersion": "버전 링크 복사",
    "settings.description": "여행 정보를 수정하거나 이야기를 업데이트하세요",
    "settings.updateStory": "이야기 업데이트",
    "settings.updateDescription":
      "최신 사진으로 지도와 타임라인을 다시 만듭니다.",
    "settings.save": "변경 사항 저장",
    "settings.deleteTrip": "여행 삭제",
    "settings.selectTrip": "설정을 수정할 여행을 선택하세요.",
    "review.description": "여행에서 확인할 항목을 해결하세요",
    "review.issueCount": "확인 항목 {count}개",
    "appSettings.description": "계정 및 작업 공간 환경설정",
    "appSettings.signedIn": "로그인됨",
    "publicStory.eyebrow": "공개된 이야기",
    "publicStory.loading": "이야기 불러오는 중",
    "publicStory.unavailable": "이야기를 사용할 수 없습니다",
    "publicStory.notAvailable": "이 이야기는 현재 볼 수 없습니다.",
    "publicStory.myTrips": "내 여행",
    "publicStory.home": "TripWeave 홈",
    "publicStory.title": "TripWeave 이야기",
    "publicStory.defaultTitle": "여행 이야기",
    "publicStory.version": "공개 버전 {number}",
    "publicStory.publishedBy": "게시자: {name}",
    "publicStory.view": "이야기 보기",
    "publicStory.slideshow": "슬라이드쇼",
    "publicStory.save": "저장",
    "publicStory.saved": "저장됨",
    "publicStory.removeSaved": "저장한 이야기에서 제거",
    "publicStory.saveStory": "이야기 저장",
    "invite.eyebrow": "TripWeave 초대",
    "invite.loading": "초대 불러오는 중",
    "invite.description":
      "{role}(으)로 이 여행에 참여하려면 로그인하거나 계정을 만드세요.",
    "invite.signedInAs": "{name}(으)로 로그인되어 있습니다.",
    "invite.join": "여행 참여",
    "invite.accountMode": "초대 계정 방식",
    "invite.login": "로그인",
    "invite.createAccount": "계정 만들기",
    "invite.createAndJoin": "계정 만들고 참여하기",
    "invite.loginAndJoin": "로그인하고 참여하기",
    "contributor.loading": "기여 페이지 불러오는 중",
    "contributor.eyebrow": "기여자 업로드",
    "contributor.welcome": "환영합니다, {name}님",
    "contributor.unavailable": "기여 기능을 사용할 수 없습니다",
    "contributor.addImages": "JPEG 또는 HEIC 이미지 추가",
    "contributor.ownUploads": "여기에는 내 업로드만 표시됩니다.",
    "contributor.uploadGrantUnavailable": "업로드 권한을 사용할 수 없습니다",
    "contributor.tooManyFiles":
      "이 여행에는 사진을 최대 {max}장까지 추가할 수 있습니다. 사진을 더 추가하려면 업로드를 삭제하거나 취소하세요.",
    "media.noProcessed": "아직 처리된 미디어가 없습니다.",
    "media.openPhoto": "{name} 열기",
    "media.photo": "사진",
    "media.untitled": "제목 없는 이미지",
    "media.stack": "{count}장 묶음",
    "media.representative": "대표 사진",
    "media.visibility": "공개 범위",
    "media.visibilityLabel": "사진 공개 범위",
    "media.memberOnly": "구성원만",
    "media.public": "공개",
    "media.visibilityHelp": "사진 공개 범위 도움말",
    "media.whoCanSee": "이 사진을 볼 수 있는 사람",
    "media.memberOnlyDescription":
      "구성원만을 선택하면 이 여행 안에서만 볼 수 있습니다. 공개를 선택하면 공개된 이야기에 표시될 수 있습니다.",
    "media.sanitizedDescription":
      "공개된 이야기에는 원본 사진이 아닌 개인정보가 정리된 파생 이미지가 사용됩니다.",
    "media.closeVisibilityHelp": "사진 공개 범위 도움말 닫기",
    "media.captured": "촬영 시각",
    "media.gps": "GPS",
    "media.present": "있음",
    "media.notFound": "없음",
    "media.update": "수정",
    "media.dimensions": "크기",
    "media.unknown": "알 수 없음",
    "media.retryProcessing": "처리 다시 시도",
    "media.deletePhoto": "사진 삭제",
    "media.adjustLocation": "사진 위치 수정",
    "media.locationEyebrow": "사진 위치",
    "media.photoFallback": "사진",
    "media.locationInstruction":
      "원하는 장소가 가운데 핀 아래에 오도록 지도를 움직이세요.",
    "media.selectedLocation": "선택한 위치",
    "media.currentLocation": "파란 점: 현재 사진 위치",
    "media.noLocation": "이 사진에는 아직 저장된 위치가 없습니다.",
    "media.saving": "저장 중…",
    "media.useLocation": "이 위치 사용",
    "media.similarTitle": "유사한 사진 묶음",
    "media.similarDescription": "중복 및 거의 중복된 사진도 모두 보존됩니다.",
    "media.versions": "버전 {count}개",
    "media.confidence": "신뢰도",
    "media.technical": "기술 점수",
    "media.similarity": "유사도",
    "media.useRepresentative": "대표 사진으로 사용",
    "review.noRun": "아직 재구성 실행이 없습니다.",
    "review.days": "일",
    "review.stops": "장소",
    "review.items": "검토 항목",
    "review.inbox": "검토함",
    "review.openIssues": "열린 확인 항목 {count}개",
    "review.clear": "없음",
    "review.undo": "최근 편집 실행 취소",
    "review.confidence": "신뢰도",
    "review.offset": "오프셋",
    "review.support": "근거 수",
    "review.dispersion": "분산",
    "review.threshold": "기준값",
    "review.diameter": "지름",
    "review.acceptOffset": "오프셋 적용",
    "review.resolve": "해결",
    "review.dismiss": "무시",
    "review.skip": "건너뛰기",
    "review.noOpen": "열린 검토 항목이 없습니다.",
    "review.noMedia": "아직 그룹화된 사용 가능한 미디어가 없습니다.",
    "review.stop": "장소 {position}",
    "review.to": "부터",
    "review.mediaCount": "미디어 {count}개",
    "review.contributorCount": "기여자 {count}명",
    "review.moment": "순간 {position}",
    "admin.dashboard": "운영 대시보드",
    "admin.loading": "운영 대시보드 불러오는 중",
    "admin.accessRequired": "운영자 권한이 필요합니다",
    "admin.accessDescription": "운영자 권한이 설정된 계정으로 로그인하세요.",
    "admin.overview": "운영 현황",
    "admin.overviewDescription": "사용량, 사용자 활동 및 할당량 제어",
    "admin.last30Days": "최근 30일",
    "admin.usageSummary": "사용량 요약",
    "admin.users": "사용자",
    "admin.todaySignedIn": "오늘 로그인한 사용자",
    "admin.todayViews": "오늘 이야기 조회 수",
    "admin.activity": "일별 활동",
    "admin.activityDescription":
      "새 계정, 콘텐츠 생성 및 공개된 이야기 도달 현황",
    "admin.date": "날짜",
    "admin.newUsers": "신규 사용자",
    "admin.newTrips": "신규 여행",
    "admin.storyViews": "이야기 조회 수",
    "admin.tripsViewed": "조회된 여행",
    "admin.distributions": "사용량 분포",
    "admin.distributionsDescription":
      "사용자와 여행별 사용량 분포를 확인합니다.",
    "admin.userTrips": "사용자별 여행",
    "admin.userPhotos": "사용자별 사진",
    "admin.photosPerTrip": "여행별 사진",
    "admin.average": "평균 {value}",
    "admin.tiers": "티어 관리",
    "admin.tiersDescription":
      "요금제 한도를 검토하고 개별 계정을 업데이트합니다.",
    "admin.unlimited": "무제한",
    "admin.monthly": "월간",
    "admin.userManagement": "사용자 관리",
    "admin.userManagementDescription":
      "계정을 찾아 사용량을 확인하고 티어 변경을 저장합니다.",
    "admin.findUser": "사용자 찾기",
    "admin.findUserDescription":
      "이메일로 검색해 사용량을 확인하고 티어를 변경하세요.",
    "admin.searchEmail": "이메일로 검색",
    "admin.searchUsers": "사용자 검색",
    "admin.user": "사용자",
    "admin.usage": "사용량",
    "admin.tier": "티어",
    "admin.tierFor": "{email}의 티어",
    "admin.updating": "업데이트 중...",
    "admin.updateTier": "티어 업데이트",
    "admin.createTier": "티어 만들기",
    "admin.internalId": "내부 ID(슬러그)",
    "admin.internalIdHint":
      "안정적인 기계 판독용 식별자입니다. 영문 소문자, 숫자, 하이픈을 사용하세요.",
    "admin.displayName": "표시 이름",
    "admin.maxTrips": "최대 여행 수(비워 두면 무제한)",
    "admin.maxPhotos": "최대 사진 수(비워 두면 무제한)",
    "admin.monthlyBytes": "월간 업로드 바이트",
    "story.loading": "불러오는 중...",
    "story.empty":
      "사진을 추가한 뒤 이야기를 새로고침해 지도와 타임라인을 만드세요.",
    "story.selectedDayControls": "선택한 날짜 제어",
    "story.allDays": "모든 날짜",
    "story.browsePhotos": "{date} 사진 보기",
    "story.photos": "사진",
    "story.selectedArea": "선택한 영역",
    "story.selectedStop": "선택한 장소",
    "story.selectedDay": "선택한 날짜",
    "story.mapNote": "지도 메모",
    "story.noStop": "선택한 장소가 없습니다",
    "story.stopNote": "장소 메모",
    "story.dayNote": "날짜 메모",
    "story.timeline": "타임라인",
    "story.timelineDescription":
      "날짜, 장소, 사진의 순간을 따라 여행 경로를 살펴보세요.",
    "story.follow": "따라가기",
    "story.play": "재생",
    "story.browseAllPhotos": "사진 둘러보기",
    "story.controls": "이야기 제어",
    "story.wholeTrip": "전체 여행",
    "story.days": "여행 날짜",
    "story.all": "전체",
    "story.viewMode": "보기 모드",
    "story.traveler": "여행자",
    "story.everyone": "모두",
    "story.tripPhotos": "여행 사진",
    "story.groupedPhotos": "장소별 사진 {count}장",
    "story.browseDayPhotos": "이 날짜의 사진 보기",
    "story.chronologicalTimeline": "시간순 타임라인",
    "story.timelineDays": "타임라인 날짜",
  },
} as const;

export type MessageKey = keyof (typeof messages)["en"];

let runtimeLocale: Locale = "en";

export function localeTag(locale: Locale = runtimeLocale): "en-US" | "ko-KR" {
  return locale === "ko" ? "ko-KR" : "en-US";
}

export function uiLocale(): "en-US" | "ko-KR" {
  return localeTag();
}

export function browserLocale(
  languages: readonly string[] | undefined,
): Locale {
  return languages?.some((language) => language.toLowerCase().startsWith("ko"))
    ? "ko"
    : "en";
}

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  const setLocale = (nextLocale: Locale) => {
    runtimeLocale = nextLocale;
    setLocaleState(nextLocale);
    window.localStorage.setItem(localeStorageKey, nextLocale);
  };

  useEffect(() => {
    const storedLocale = window.localStorage.getItem(localeStorageKey);
    const nextLocale: Locale = supportedLocales.includes(storedLocale as Locale)
      ? (storedLocale as Locale)
      : browserLocale(navigator.languages);
    runtimeLocale = nextLocale;
    startTransition(() => setLocaleState(nextLocale));
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      t: (key, values) => interpolateMessage(messages[locale][key], values),
    }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function interpolateMessage(
  message: string,
  values: Record<string, string | number> | undefined,
): string {
  if (!values) return message;
  return message.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    name in values ? String(values[name]) : placeholder,
  );
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return value;
}

export function LanguageSelector({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className={className ?? "language-selector"}>
      <span className="sr-only">{t("language.label")}</span>
      <select
        aria-label={t("language.label")}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        <option value="en">English</option>
        <option value="ko">한국어</option>
      </select>
    </label>
  );
}
