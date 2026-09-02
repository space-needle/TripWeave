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
