/**
 * eweather-feed-card
 *
 * A Lovelace card for the hacs_eweather integration. Shows the most recent
 * post from the eweather feed sensor with its timestamp, and a swipeable
 * carousel for the post's photos. Optional arrows let you page through the
 * older posts exposed in the sensor's `posts` attribute.
 *
 * The integration serves and registers this file automatically — no manual
 * resource configuration is needed.
 *
 * Card config:
 *   type: custom:eweather-feed-card
 *   entity: sensor.eweather_forecast_feed   (required)
 *   title: eweather                         (optional; empty string hides it)
 *   show_post_nav: true                     (optional; ‹ › paging over posts)
 *   image_height: 300                       (optional; carousel height in px)
 */

const CARD_TAG = "eweather-feed-card";
const EDITOR_TAG = "eweather-feed-card-editor";

const DEFAULTS = {
  title: "eweather",
  show_post_nav: true,
  image_height: 300,
};

class EweatherFeedCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._postIndex = 0;
    this._photoIndex = 0;
    this._expanded = false;
    this._currentPostId = null;
    this._renderKey = null;
    this._touchStartX = null;
    this._touchStartY = null;
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("eweather-feed-card: 'entity' is required");
    }
    this._config = { ...DEFAULTS, ...config };
    this._postIndex = 0;
    this._photoIndex = 0;
    this._expanded = false;
    this._renderKey = null;
    if (this._hass) {
      this._update();
    }
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  connectedCallback() {
    // Keep the relative timestamp fresh without a full re-render.
    this._clock = window.setInterval(() => this._refreshRelativeTime(), 60000);
  }

  disconnectedCallback() {
    window.clearInterval(this._clock);
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto" };
  }

  static getConfigElement() {
    return document.createElement(EDITOR_TAG);
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass?.states || {}).find(
      (id) =>
        id.startsWith("sensor.") &&
        Array.isArray(hass.states[id].attributes?.posts),
    );
    return { entity: entity || "sensor.eweather_forecast_feed" };
  }

  // -- Data helpers ---------------------------------------------------------

  _stateObj() {
    return this._hass?.states?.[this._config?.entity];
  }

  _posts() {
    const posts = this._stateObj()?.attributes?.posts;
    return Array.isArray(posts) ? posts : [];
  }

  _postImages(post) {
    // Post URLs come from the feed and are semi-untrusted; only http(s) may
    // reach an <img> src or window.open.
    const images = Array.isArray(post.images) ? post.images : [];
    return images
      .map((url) => (typeof url === "string" ? safeHttpUrl(url) : null))
      .filter(Boolean);
  }

  _locale() {
    return this._hass?.locale?.language || navigator.language || "en";
  }

  _relativeTime(date) {
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const rtf = new Intl.RelativeTimeFormat(this._locale(), {
      numeric: "auto",
    });
    const table = [
      [60, "second", 1],
      [3600, "minute", 60],
      [86400, "hour", 3600],
      [604800, "day", 86400],
      [2629800, "week", 604800],
      [31557600, "month", 2629800],
      [Infinity, "year", 31557600],
    ];
    const abs = Math.abs(seconds);
    for (const [limit, unit, divisor] of table) {
      if (abs < limit) {
        return rtf.format(Math.round(seconds / divisor), unit);
      }
    }
    return "";
  }

  _absoluteTime(date) {
    return new Intl.DateTimeFormat(this._locale(), {
      weekday: "short",
      month: "short",
      day: "numeric",
      year:
        date.getFullYear() === new Date().getFullYear()
          ? undefined
          : "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }

  // -- Rendering ------------------------------------------------------------

  _update() {
    if (!this._config || !this._hass) {
      return;
    }
    const stateObj = this._stateObj();
    if (!stateObj) {
      this._renderIfChanged(`error|missing|${this._config.entity}`, () =>
        this._renderError(
          `Entity not found: ${this._config.entity}`,
          "Check the card's entity setting.",
        ),
      );
      return;
    }
    const posts = this._posts();
    if (!posts.length) {
      this._renderIfChanged("error|empty", () =>
        this._renderError(
          "No posts in the feed yet",
          "The sensor has not reported any posts.",
        ),
      );
      return;
    }

    // Follow the selected post by id across feed updates (new posts shift the
    // list); fall back to the newest post when it drops out of the window.
    let index = this._currentPostId
      ? posts.findIndex((p) => p.id === this._currentPostId)
      : -1;
    if (index === -1) {
      index = 0;
    }
    this._postIndex = index;
    const post = posts[index];
    if (post.id !== this._currentPostId) {
      this._currentPostId = post.id;
      this._photoIndex = 0;
      this._expanded = false;
    }
    const images = this._postImages(post);
    if (this._photoIndex >= images.length) {
      this._photoIndex = Math.max(0, images.length - 1);
    }

    const key = [
      this._config.entity,
      stateObj.last_updated,
      post.id,
      this._postIndex,
      this._photoIndex,
      this._expanded,
    ].join("|");
    if (key === this._renderKey) {
      return;
    }
    this._renderKey = key;
    this._render(posts, post, images);
  }

  _renderIfChanged(key, render) {
    if (key === this._renderKey) {
      return;
    }
    this._renderKey = key;
    render();
  }

  _renderError(title, detail) {
    this.shadowRoot.innerHTML = `
      <style>${EweatherFeedCard._styles()}</style>
      <ha-card>
        <div class="empty">
          <div class="empty-title">${escapeHtml(title)}</div>
          <div class="empty-detail">${escapeHtml(detail)}</div>
        </div>
      </ha-card>`;
  }

  _render(posts, post, images) {
    const created = post.created ? new Date(post.created) : null;
    const createdValid = created && !Number.isNaN(created.getTime());

    const header = this._headerHtml(posts);
    const carousel = this._carouselHtml(images, post);
    const body = this._bodyHtml(post, createdValid ? created : null);

    // innerHTML replacement destroys the focused element; put focus back so
    // keyboard navigation keeps working across renders.
    const active = this.shadowRoot.activeElement;
    const focusId =
      active?.id || (active?.classList?.contains("carousel") ? "carousel" : null);

    this.shadowRoot.innerHTML = `
      <style>${EweatherFeedCard._styles()}</style>
      <ha-card>
        ${header}
        ${carousel}
        ${body}
      </ha-card>`;

    this._wireEvents(posts.length, images);

    if (focusId) {
      const el =
        focusId === "carousel"
          ? this.shadowRoot.querySelector(".carousel")
          : this.shadowRoot.querySelector(`#${CSS.escape(focusId)}`);
      el?.focus();
    }
  }

  _headerHtml(posts) {
    const title = this._config.title;
    const nav =
      this._config.show_post_nav && posts.length > 1
        ? `<div class="post-nav">
             <button class="nav-btn" id="prev-post" aria-label="Newer post"
               ${this._postIndex === 0 ? "disabled" : ""}>&#8249;</button>
             <span class="nav-pos">${this._postIndex + 1} / ${posts.length}</span>
             <button class="nav-btn" id="next-post" aria-label="Older post"
               ${this._postIndex >= posts.length - 1 ? "disabled" : ""}>&#8250;</button>
           </div>`
        : "";
    if (!title && !nav) {
      return "";
    }
    return `<div class="header">
        <div class="card-title">${escapeHtml(title || "")}</div>
        ${nav}
      </div>`;
  }

  _carouselHtml(images, post) {
    if (!images.length) {
      return "";
    }
    const height = Math.max(
      120,
      Number(this._config.image_height) || DEFAULTS.image_height,
    );
    const slides = images
      .map(
        (url, i) => `
        <div class="slide">
          <img src="${escapeHtml(url)}" loading="lazy" data-url="${escapeHtml(url)}"
            alt="${escapeHtml(post.title || "Post photo")} (${i + 1} of ${images.length})" />
        </div>`,
      )
      .join("");
    const dots =
      images.length > 1
        ? `<div class="dots">
            ${images
              .map(
                (_, i) =>
                  `<button class="dot ${i === this._photoIndex ? "active" : ""}"
                     data-index="${i}" aria-label="Photo ${i + 1}"></button>`,
              )
              .join("")}
          </div>`
        : "";
    const arrows =
      images.length > 1
        ? `<button class="arrow left" id="prev-photo" aria-label="Previous photo">&#8249;</button>
           <button class="arrow right" id="next-photo" aria-label="Next photo">&#8250;</button>
           <div class="photo-counter">${this._photoIndex + 1}/${images.length}</div>`
        : "";
    return `
      <div class="carousel" style="height:${height}px" tabindex="0"
           aria-label="Post photos">
        <div class="track" style="transform: translateX(-${this._photoIndex * 100}%)">
          ${slides}
        </div>
        ${arrows}
        ${dots}
      </div>`;
  }

  _bodyHtml(post, created) {
    const metaBits = [];
    if (post.author) {
      metaBits.push(`<span class="author">${escapeHtml(post.author)}</span>`);
    }
    if (post.official) {
      metaBits.push(`<span class="badge" title="Official eweather post">&#10003; official</span>`);
    }
    if (post.category) {
      metaBits.push(`<span class="chip">${escapeHtml(post.category)}</span>`);
    }
    if (created) {
      metaBits.push(
        `<span class="rel-time" title="${escapeHtml(this._absoluteTime(created))}"
           data-created="${created.toISOString()}">${escapeHtml(this._relativeTime(created))}</span>`,
      );
    }

    const text = (post.text || "").trim();
    const needsClamp = text.length > 280 || text.split("\n").length > 4;
    return `
      <div class="content">
        <div class="meta">${metaBits.join('<span class="sep">·</span>')}</div>
        ${post.title ? `<div class="post-title">${escapeHtml(post.title)}</div>` : ""}
        ${
          text
            ? `<div class="post-text ${needsClamp && !this._expanded ? "clamped" : ""}">${escapeHtml(text)}</div>
               ${needsClamp ? `<button class="expand" id="toggle-text">${this._expanded ? "Show less" : "Show more"}</button>` : ""}`
            : ""
        }
        ${created ? `<div class="footer">${escapeHtml(this._absoluteTime(created))}</div>` : ""}
      </div>`;
  }

  // -- Events ---------------------------------------------------------------

  _wireEvents(postCount, images) {
    const root = this.shadowRoot;
    const on = (selector, handler) => {
      const el = root.querySelector(selector);
      if (el) {
        el.addEventListener("click", handler);
      }
    };

    on("#prev-post", () => this._setPost(this._postIndex - 1, postCount));
    on("#next-post", () => this._setPost(this._postIndex + 1, postCount));
    on("#prev-photo", () => this._setPhoto(this._photoIndex - 1, images.length));
    on("#next-photo", () => this._setPhoto(this._photoIndex + 1, images.length));
    on("#toggle-text", () => {
      this._expanded = !this._expanded;
      this._renderKey = null;
      this._update();
    });

    root.querySelectorAll(".dot").forEach((dot) => {
      dot.addEventListener("click", () =>
        this._setPhoto(Number(dot.dataset.index), images.length),
      );
    });

    root.querySelectorAll(".slide img").forEach((img) => {
      img.addEventListener("click", () => {
        window.open(img.dataset.url, "_blank", "noopener");
      });
    });

    const carousel = root.querySelector(".carousel");
    if (carousel && images.length > 1) {
      carousel.addEventListener(
        "touchstart",
        (ev) => {
          this._touchStartX = ev.touches[0].clientX;
          this._touchStartY = ev.touches[0].clientY;
        },
        { passive: true },
      );
      carousel.addEventListener(
        "touchend",
        (ev) => {
          if (this._touchStartX === null) {
            return;
          }
          const deltaX = ev.changedTouches[0].clientX - this._touchStartX;
          const deltaY = ev.changedTouches[0].clientY - this._touchStartY;
          this._touchStartX = null;
          this._touchStartY = null;
          // Only treat horizontally-dominant gestures as swipes so vertical
          // page scrolling over the carousel doesn't flip photos.
          if (Math.abs(deltaX) > 40 && Math.abs(deltaX) > Math.abs(deltaY)) {
            this._setPhoto(
              this._photoIndex + (deltaX < 0 ? 1 : -1),
              images.length,
            );
          }
        },
        { passive: true },
      );
      carousel.addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowLeft") {
          this._setPhoto(this._photoIndex - 1, images.length);
        } else if (ev.key === "ArrowRight") {
          this._setPhoto(this._photoIndex + 1, images.length);
        }
      });
    }
  }

  _setPost(index, count) {
    if (index < 0 || index >= count) {
      return;
    }
    const posts = this._posts();
    this._postIndex = index;
    this._currentPostId = posts[index]?.id ?? null;
    this._photoIndex = 0;
    this._expanded = false;
    this._renderKey = null;
    this._update();
  }

  _setPhoto(index, count) {
    if (index < 0 || index >= count) {
      return;
    }
    this._photoIndex = index;
    this._renderKey = null;
    this._update();
  }

  _refreshRelativeTime() {
    const el = this.shadowRoot?.querySelector(".rel-time");
    if (el?.dataset.created) {
      el.textContent = this._relativeTime(new Date(el.dataset.created));
    }
  }

  // -- Styles ---------------------------------------------------------------

  static _styles() {
    return `
      ha-card { overflow: hidden; }
      .header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px 8px;
      }
      .card-title {
        font-size: 1.15em; font-weight: 500;
        color: var(--primary-text-color);
      }
      .post-nav { display: flex; align-items: center; gap: 4px; }
      .nav-pos {
        font-size: 0.85em; color: var(--secondary-text-color);
        min-width: 44px; text-align: center;
      }
      .nav-btn {
        background: none; border: none; cursor: pointer;
        font-size: 1.4em; line-height: 1; padding: 2px 8px;
        color: var(--primary-text-color); border-radius: 4px;
      }
      .nav-btn:hover { background: var(--secondary-background-color); }
      .nav-btn[disabled] { opacity: 0.3; cursor: default; }
      .nav-btn[disabled]:hover { background: none; }

      .carousel {
        position: relative; overflow: hidden; outline: none;
        background: var(--secondary-background-color);
      }
      .track {
        display: flex; height: 100%;
        transition: transform 0.25s ease;
      }
      .slide { flex: 0 0 100%; height: 100%; }
      .slide img {
        width: 100%; height: 100%; object-fit: contain;
        display: block; cursor: pointer;
      }
      .arrow {
        position: absolute; top: 50%; transform: translateY(-50%);
        border: none; cursor: pointer; font-size: 1.6em; line-height: 1;
        width: 34px; height: 34px; border-radius: 50%;
        background: rgba(0, 0, 0, 0.45); color: #fff;
        display: flex; align-items: center; justify-content: center;
        opacity: 0.75;
      }
      .arrow:hover { opacity: 1; }
      .arrow.left { left: 8px; }
      .arrow.right { right: 8px; }
      .photo-counter {
        position: absolute; top: 8px; right: 10px;
        background: rgba(0, 0, 0, 0.45); color: #fff;
        font-size: 0.75em; padding: 2px 8px; border-radius: 10px;
      }
      .dots {
        position: absolute; bottom: 6px; left: 0; right: 0;
        display: flex; justify-content: center; gap: 6px;
      }
      .dot {
        width: 8px; height: 8px; border-radius: 50%;
        border: none; padding: 0; cursor: pointer;
        background: rgba(255, 255, 255, 0.55);
        box-shadow: 0 0 2px rgba(0, 0, 0, 0.6);
      }
      .dot.active { background: #fff; }

      .content { padding: 12px 16px 16px; }
      .meta {
        display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
        font-size: 0.85em; color: var(--secondary-text-color);
        margin-bottom: 6px;
      }
      .sep { opacity: 0.6; }
      .author { font-weight: 500; color: var(--primary-text-color); }
      .badge {
        color: var(--success-color, #0f9d58); font-weight: 500;
      }
      .chip {
        background: var(--secondary-background-color);
        border-radius: 10px; padding: 1px 8px;
      }
      .rel-time { cursor: default; }
      .post-title {
        font-weight: 600; font-size: 1.05em; margin-bottom: 4px;
        color: var(--primary-text-color);
      }
      .post-text {
        white-space: pre-wrap; overflow-wrap: anywhere;
        color: var(--primary-text-color); font-size: 0.95em;
        line-height: 1.45;
      }
      .post-text.clamped {
        display: -webkit-box; -webkit-line-clamp: 4;
        -webkit-box-orient: vertical; overflow: hidden;
      }
      .expand {
        background: none; border: none; padding: 4px 0 0; cursor: pointer;
        color: var(--primary-color); font-size: 0.85em; font-weight: 500;
      }
      .footer {
        margin-top: 10px; font-size: 0.8em;
        color: var(--secondary-text-color);
      }
      .empty { padding: 24px 16px; text-align: center; }
      .empty-title {
        font-weight: 500; color: var(--primary-text-color);
        margin-bottom: 4px;
      }
      .empty-detail {
        font-size: 0.85em; color: var(--secondary-text-color);
      }
    `;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function safeHttpUrl(value) {
  let url;
  try {
    url = new URL(value, window.location.href);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:"
    ? url.href
    : null;
}

// -- Config editor (visual editor support) -----------------------------------

const EDITOR_SCHEMA = [
  {
    name: "entity",
    required: true,
    selector: { entity: { domain: "sensor" } },
  },
  { name: "title", selector: { text: {} } },
  { name: "show_post_nav", selector: { boolean: {} } },
  {
    name: "image_height",
    selector: { number: { min: 120, max: 800, step: 10, mode: "box" } },
  },
];

const EDITOR_LABELS = {
  entity: "Feed sensor",
  title: "Card title",
  show_post_nav: "Allow paging through older posts",
  image_height: "Photo carousel height (px)",
};

class EweatherFeedCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
    }
  }

  _render() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        EDITOR_LABELS[schema.name] || schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        // Keep stored YAML minimal: drop options left at their default.
        const config = { type: `custom:${CARD_TAG}` };
        for (const [key, value] of Object.entries(ev.detail.value || {})) {
          if (
            key === "entity" ||
            DEFAULTS[key] === undefined ||
            value !== DEFAULTS[key]
          ) {
            config[key] = value;
          }
        }
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this.appendChild(this._form);
    }
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = { ...DEFAULTS, ...this._config };
    if (this._hass) {
      this._form.hass = this._hass;
    }
  }
}

if (!customElements.get(CARD_TAG)) {
  customElements.define(CARD_TAG, EweatherFeedCard);
}
if (!customElements.get(EDITOR_TAG)) {
  customElements.define(EDITOR_TAG, EweatherFeedCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TAG)) {
  window.customCards.push({
    type: CARD_TAG,
    name: "EWeather Feed Card",
    description:
      "Shows the latest eweather post with its timestamp and a swipeable photo carousel.",
    preview: false,
    documentationURL: "https://github.com/brevans/hacs-eweather",
  });
}
