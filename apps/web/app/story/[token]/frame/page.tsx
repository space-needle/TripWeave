import { notFound } from "next/navigation";
import type { CSSProperties } from "react";
import type { PublicStoryResponse } from "../../../api-types";
import {
  buildFrameStory,
  frameStoryApiBaseUrl,
  publicStoryEndpoint,
  type FrameScene,
} from "../../../frame-story";

type FramePageProps = {
  params: Promise<{ token: string }>;
};

export default async function StoryFramePage({ params }: FramePageProps) {
  const { token } = await params;
  const story = await loadPublicStory(token);
  const frameStory = buildFrameStory(story);
  const scenes = frameStory.scenes;

  if (scenes.length === 0) {
    return (
      <main className="legacy-frame-shell">
        <FrameStyles />
        <section className="legacy-frame-empty">
          <p>TripWeave frame</p>
          <h1>{frameStory.title}</h1>
          <span>No published photos are available for this story.</span>
        </section>
      </main>
    );
  }

  return (
    <main className="legacy-frame-shell">
      <FrameStyles />
      <section
        className="legacy-frame-stage"
        aria-label={`${frameStory.title} frame slideshow`}
      >
        {scenes.map((scene, index) => (
          <FrameSceneView key={scene.id} scene={scene} active={index === 0} />
        ))}
        <header className="legacy-frame-brand">
          <p>TripWeave</p>
          <h1>{frameStory.title}</h1>
          <span>{frameStory.subtitle}</span>
        </header>
        <footer className="legacy-frame-caption" aria-live="polite">
          <p id="legacy-frame-kicker">{sceneKicker(scenes[0])}</p>
          <h2 id="legacy-frame-title">{scenes[0].title}</h2>
          <span id="legacy-frame-subtitle">{scenes[0].subtitle}</span>
        </footer>
        <div className="legacy-frame-progress" aria-hidden="true">
          <span id="legacy-frame-progress-bar" />
        </div>
      </section>
      <script
        dangerouslySetInnerHTML={{
          __html: `window.__TRIPWEAVE_FRAME_SCENES=${safeJson(
            scenes.map((scene) => ({
              id: scene.id,
              type: scene.type,
              title: scene.title,
              subtitle: scene.subtitle,
              durationMs: scene.durationMs,
            })),
          )};`,
        }}
      />
      <script dangerouslySetInnerHTML={{ __html: legacyFrameScript }} />
    </main>
  );
}

async function loadPublicStory(token: string): Promise<PublicStoryResponse> {
  const response = await fetch(
    publicStoryEndpoint(frameStoryApiBaseUrl(), token),
    {
      cache: "no-store",
      headers: { accept: "application/json" },
    },
  );
  if (response.status === 404 || response.status === 410) {
    notFound();
  }
  if (!response.ok) {
    throw new Error(`Story frame request failed with ${response.status}`);
  }
  return (await response.json()) as PublicStoryResponse;
}

function FrameSceneView({
  scene,
  active,
}: {
  scene: FrameScene;
  active: boolean;
}) {
  if (scene.type === "photo") {
    return (
      <article
        className={`legacy-frame-scene legacy-frame-photo${
          active ? " is-active" : ""
        }`}
        data-frame-scene={scene.id}
        aria-hidden={active ? "false" : "true"}
      >
        <div
          className="legacy-frame-photo-image"
          role="img"
          aria-label={scene.title}
          style={
            {
              backgroundImage: `url("${scene.imageUrl}")`,
            } as CSSProperties
          }
        />
      </article>
    );
  }

  return (
    <article
      className={`legacy-frame-scene legacy-frame-map${
        active ? " is-active" : ""
      }`}
      data-frame-scene={scene.id}
      aria-hidden={active ? "false" : "true"}
    >
      <svg viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <defs>
          <pattern
            id={`grid-${scene.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`}
            width="10"
            height="10"
            patternUnits="userSpaceOnUse"
          >
            <path d="M 10 0 L 0 0 0 10" />
          </pattern>
        </defs>
        <rect
          className="legacy-frame-map-grid"
          width="100"
          height="100"
          rx="3"
        />
        {scene.routes.map((route) => (
          <polyline
            key={route.id}
            className="legacy-frame-route"
            points={route.points}
          />
        ))}
        {scene.stops.map((stop) => (
          <g
            key={stop.id}
            className={`legacy-frame-stop${stop.active ? " is-current" : ""}`}
            transform={`translate(${stop.x} ${stop.y})`}
          >
            <circle r={stop.active ? 5.4 : 4.2} />
            <text y="1.2">{stop.position}</text>
          </g>
        ))}
      </svg>
      <ol>
        {scene.stops.map((stop) => (
          <li key={stop.id} className={stop.active ? "is-current" : ""}>
            <span>{stop.position}</span>
            {stop.label}
          </li>
        ))}
      </ol>
    </article>
  );
}

function FrameStyles() {
  return (
    <style>{`
html, body {
  margin: 0;
  min-height: 100%;
  background: #080a0d;
}
body {
  overflow: hidden;
}
.legacy-frame-shell {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  overflow: hidden;
  background: #080a0d;
  color: #ffffff;
  font-family: Arial, Helvetica, sans-serif;
}
.legacy-frame-stage,
.legacy-frame-scene {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
}
.legacy-frame-scene {
  opacity: 0;
  z-index: 0;
  background: #0d1115;
  transition: opacity 1400ms ease;
}
.legacy-frame-scene.is-active {
  opacity: 1;
  z-index: 1;
}
.legacy-frame-photo-image {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background-position: center center;
  background-repeat: no-repeat;
  background-size: contain;
  transform: scale(1);
}
.legacy-frame-scene.is-active .legacy-frame-photo-image {
  animation: legacy-frame-photo-drift 9000ms ease-out forwards;
}
.legacy-frame-photo:before {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background: radial-gradient(circle at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.45) 100%);
  z-index: 1;
}
.legacy-frame-map {
  background: #dfe7df;
  color: #18211d;
}
.legacy-frame-map:after {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  background: linear-gradient(to bottom, rgba(255,255,255,0.22), rgba(0,0,0,0.06));
  pointer-events: none;
}
.legacy-frame-map svg {
  position: absolute;
  left: 6%;
  top: 8%;
  width: 62%;
  height: 78%;
}
.legacy-frame-map-grid {
  fill: #e7efe8;
  stroke: #c4d0c6;
  stroke-width: 0.4;
}
.legacy-frame-route {
  fill: none;
  stroke: #d9793d;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.35;
  stroke-dasharray: 2 1.4;
}
.legacy-frame-stop circle {
  fill: #1f6a5b;
  stroke: #ffffff;
  stroke-width: 1;
}
.legacy-frame-stop.is-current circle {
  fill: #d75736;
}
.legacy-frame-stop text {
  fill: #ffffff;
  font-size: 4.4px;
  font-weight: 700;
  text-anchor: middle;
}
.legacy-frame-map ol {
  position: absolute;
  right: 5%;
  top: 13%;
  bottom: 22%;
  width: 27%;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: hidden;
}
.legacy-frame-map li {
  margin: 0 0 10px;
  color: #314039;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.25;
}
.legacy-frame-map li span {
  display: inline-block;
  width: 25px;
  height: 25px;
  margin-right: 8px;
  border-radius: 20px;
  background: #1f6a5b;
  color: #ffffff;
  text-align: center;
  line-height: 25px;
}
.legacy-frame-map li.is-current {
  color: #9f3921;
}
.legacy-frame-map li.is-current span {
  background: #d75736;
}
.legacy-frame-brand,
.legacy-frame-caption {
  position: absolute;
  left: 4%;
  right: 4%;
  z-index: 3;
  text-shadow: 0 2px 18px rgba(0,0,0,0.76);
}
.legacy-frame-brand {
  top: 28px;
}
.legacy-frame-brand p,
.legacy-frame-caption p,
.legacy-frame-brand h1,
.legacy-frame-caption h2,
.legacy-frame-brand span,
.legacy-frame-caption span {
  margin: 0;
}
.legacy-frame-brand p,
.legacy-frame-caption p {
  color: #f5b45f;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}
.legacy-frame-brand h1 {
  margin-top: 4px;
  font-size: 30px;
  line-height: 1.05;
}
.legacy-frame-brand span {
  display: block;
  margin-top: 6px;
  max-width: 720px;
  color: rgba(255,255,255,0.78);
  font-size: 16px;
  font-weight: 700;
}
.legacy-frame-caption {
  bottom: 34px;
  max-width: 760px;
}
.legacy-frame-caption h2 {
  margin-top: 5px;
  font-size: 42px;
  line-height: 1;
}
.legacy-frame-caption span {
  display: block;
  margin-top: 8px;
  color: rgba(255,255,255,0.82);
  font-size: 18px;
  font-weight: 700;
}
.legacy-frame-progress {
  position: absolute;
  left: 4%;
  right: 4%;
  bottom: 18px;
  z-index: 4;
  height: 3px;
  overflow: hidden;
  background: rgba(255,255,255,0.24);
}
.legacy-frame-progress span {
  display: block;
  width: 0%;
  height: 100%;
  background: #f5b45f;
}
.legacy-frame-empty {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  display: table;
  width: 100%;
  height: 100%;
  text-align: center;
}
.legacy-frame-empty > * {
  display: block;
  margin: 0 auto 10px;
  max-width: 680px;
}
.legacy-frame-empty p {
  margin-top: 28vh;
  color: #f5b45f;
  font-weight: 800;
  text-transform: uppercase;
}
.legacy-frame-empty h1 {
  font-size: 36px;
}
.legacy-frame-empty span {
  color: rgba(255,255,255,0.75);
}
@keyframes legacy-frame-photo-drift {
  from { transform: scale(1); }
  to { transform: scale(1.045); }
}
@media (max-width: 760px) {
  .legacy-frame-brand h1 { font-size: 24px; }
  .legacy-frame-brand span { font-size: 14px; }
  .legacy-frame-caption h2 { font-size: 32px; }
  .legacy-frame-caption span { font-size: 16px; }
  .legacy-frame-map svg {
    left: 4%;
    top: 13%;
    width: 92%;
    height: 52%;
  }
  .legacy-frame-map ol {
    left: 5%;
    right: 5%;
    top: auto;
    bottom: 23%;
    width: auto;
    height: 72px;
  }
  .legacy-frame-map li {
    display: inline-block;
    margin-right: 16px;
    font-size: 15px;
  }
}
`}</style>
  );
}

function sceneKicker(scene: FrameScene): string {
  return scene.type === "map" ? "Map scene" : "Trip photo";
}

function safeJson(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

const legacyFrameScript = `(function () {
  var scenes = window.__TRIPWEAVE_FRAME_SCENES || [];
  if (!scenes.length) return;
  var index = 0;
  var timer = null;
  var progressTimer = null;
  var startedAt = 0;
  var title = document.getElementById("legacy-frame-title");
  var subtitle = document.getElementById("legacy-frame-subtitle");
  var kicker = document.getElementById("legacy-frame-kicker");
  var progress = document.getElementById("legacy-frame-progress-bar");

  function bySceneId(id) {
    var nodes = document.getElementsByTagName("article");
    for (var i = 0; i < nodes.length; i += 1) {
      if (nodes[i].getAttribute("data-frame-scene") === id) return nodes[i];
    }
    return null;
  }

  function setClassActive(node, active) {
    if (!node) return;
    var name = node.className.replace(/\\s*is-active/g, "");
    node.className = active ? name + " is-active" : name;
    node.setAttribute("aria-hidden", active ? "false" : "true");
  }

  function setText(node, value) {
    if (node) node.innerHTML = "";
    if (node) node.appendChild(document.createTextNode(value || ""));
  }

  function show(nextIndex) {
    var previous = scenes[index];
    var current = scenes[nextIndex];
    setClassActive(bySceneId(previous.id), false);
    setClassActive(bySceneId(current.id), true);
    index = nextIndex;
    setText(title, current.title);
    setText(subtitle, current.subtitle);
    setText(kicker, current.type === "map" ? "Map scene" : "Trip photo");
    startedAt = new Date().getTime();
    if (progress) progress.style.width = "0%";
    schedule();
  }

  function tickProgress() {
    var scene = scenes[index];
    var elapsed = new Date().getTime() - startedAt;
    var percent = Math.min(100, Math.max(0, (elapsed / scene.durationMs) * 100));
    if (progress) progress.style.width = percent + "%";
  }

  function schedule() {
    if (timer) window.clearTimeout(timer);
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = window.setInterval(tickProgress, 180);
    timer = window.setTimeout(function () {
      show((index + 1) % scenes.length);
    }, scenes[index].durationMs);
  }

  startedAt = new Date().getTime();
  schedule();
}());`;
