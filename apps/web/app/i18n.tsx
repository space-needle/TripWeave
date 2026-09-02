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
  t: (key: MessageKey) => string;
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
      t: (key) => messages[locale][key],
    }),
    [locale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
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
