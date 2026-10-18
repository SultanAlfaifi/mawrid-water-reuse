(function() {
	//#region mawrid-system/client/api.js
	var ApiError = class extends Error {
		constructor(message, code = "request_failed", status = 0) {
			super(message);
			this.name = "ApiError";
			this.code = code;
			this.status = status;
		}
	};
	async function request(path, { method = "GET", body, timeout = 12e4, binary = false } = {}) {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), timeout);
		try {
			const response = await fetch(path, {
				method,
				credentials: "same-origin",
				cache: "no-store",
				signal: controller.signal,
				headers: {
					Accept: binary ? "text/csv,application/octet-stream,application/json" : "application/json",
					...body !== void 0 ? { "Content-Type": "application/json" } : {}
				},
				...body !== void 0 ? { body: JSON.stringify(body) } : {}
			});
			if (!response.ok) {
				let payload;
				try {
					payload = await response.json();
				} catch {}
				throw new ApiError(payload?.error?.message || `تعذّر تنفيذ الطلب (HTTP ${response.status}).`, payload?.error?.code, response.status);
			}
			if (binary) return await response.blob();
			try {
				return await response.json();
			} catch {
				throw new ApiError("وصل رد غير صالح من الخدمة المحلية.", "invalid_response", response.status);
			}
		} catch (error) {
			if (error instanceof ApiError) throw error;
			if (error.name === "AbortError") throw new ApiError("استغرق الطلب وقتًا طويلًا. حدّث الحالة للتأكد مما اكتمل قبل تكراره.", "timeout");
			throw new ApiError("تعذّر الوصول إلى الخدمة المحلية. تأكد من تشغيل خادم مورد ثم أعد المحاولة.", "network_error");
		} finally {
			clearTimeout(timer);
		}
	}
	var api = {
		state: () => request("/api/state", { timeout: 3e4 }),
		sources: () => request("/api/sources", { timeout: 3e4 }),
		createSession: (sourceId, researchAck) => request("/api/sessions", {
			method: "POST",
			body: {
				source_id: sourceId,
				research_ack: researchAck
			}
		}),
		step: (count) => request("/api/replay/step", {
			method: "POST",
			body: { count }
		}),
		pause: () => request("/api/replay/pause", {
			method: "POST",
			body: {}
		}),
		plantControl: (control) => request("/api/plant/control", {
			method: "POST",
			body: control
		}),
		stop: () => request("/api/control/stop", {
			method: "POST",
			body: { note: "احتجاز يدوي من واجهة مورد المحلية" }
		}),
		reset: () => request("/api/control/reset", {
			method: "POST",
			body: {}
		}),
		acknowledge: (id) => request(`/api/alarms/${encodeURIComponent(id)}/ack`, {
			method: "POST",
			body: { note: "تمت المراجعة من واجهة مورد المحلية" }
		}),
		readings: ({ limit = 100, sessionId } = {}) => request(`/api/readings?${new URLSearchParams({
			limit: String(limit),
			...sessionId ? { session_id: sessionId } : {}
		})}`),
		alarms: () => request("/api/alarms?limit=100"),
		settings: () => request("/api/settings"),
		saveSettings: (settings) => request("/api/settings", {
			method: "PATCH",
			body: settings
		}),
		report: () => request("/api/report"),
		export: (type) => request(`/api/export/${type === "events" ? "events" : "readings"}.csv`, { binary: true })
	};
	function safeLink(value) {
		if (typeof value !== "string") return null;
		try {
			const url = new URL(value, location.origin);
			return ["http:", "https:"].includes(url.protocol) ? url.href : null;
		} catch {
			return null;
		}
	}
	//#endregion
	//#region mawrid-system/client/charts.js
	var esc$3 = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		"\"": "&quot;",
		"'": "&#39;"
	})[c]);
	var number$1 = (value) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 }).format(value);
	function sensorChart(rows, channel) {
		const points = rows.map((row, index) => ({
			index,
			value: row.channels?.[channel.key],
			row
		}));
		const finite = points.filter((point) => typeof point.value === "number" && Number.isFinite(point.value));
		if (!finite.length) return {
			svg: "",
			finiteCount: 0,
			missingCount: rows.length,
			min: null,
			max: null,
			latest: null
		};
		const width = 760, height = 245, left = 52, top = 23;
		const rawMin = Math.min(...finite.map((p) => p.value)), rawMax = Math.max(...finite.map((p) => p.value));
		const range = rawMax - rawMin, padding = range ? range * .14 : Math.max(Math.abs(rawMin) * .03, .05);
		const min = rawMin - padding, max = rawMax + padding;
		const x = (index) => left + (rows.length < 2 ? .5 : index / (rows.length - 1)) * 688;
		const y = (value) => top + (max - value) / (max - min) * 190;
		let drawing = false, path = "";
		points.forEach((point) => {
			if (typeof point.value !== "number" || !Number.isFinite(point.value)) {
				drawing = false;
				return;
			}
			path += `${drawing ? "L" : "M"}${x(point.index).toFixed(2)},${y(point.value).toFixed(2)} `;
			drawing = true;
		});
		const grid = Array.from({ length: 4 }, (_, index) => {
			const value = min + (max - min) * index / 3, yy = y(value);
			return `<line class="chart-grid" x1="${left}" y1="${yy}" x2="740" y2="${yy}"/><text class="chart-axis" x="42" y="${yy + 3}" text-anchor="end">${esc$3(number$1(value))}</text>`;
		}).join("");
		const labels = [.../* @__PURE__ */ new Set([
			0,
			Math.floor((rows.length - 1) / 2),
			rows.length - 1
		])].map((index) => `<text class="chart-axis" x="${x(index)}" y="238" text-anchor="${index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"}">${esc$3(String(rows[index]?.timestamp || "").replace("T", " ").slice(11, 19) || `#${rows[index]?.sample_index ?? index}`)}</text>`).join("");
		const dots = finite.filter((p) => p.row.prediction === 1 || finite.length === 1).map((p) => `<circle cx="${x(p.index)}" cy="${y(p.value)}" r="${p.row.prediction === 1 ? 3.5 : 3}" fill="${p.row.prediction === 1 ? "#bb7966" : "#547f52"}"><title>${esc$3(`${channel.name}: ${number$1(p.value)} ${channel.unit || ""} · ${p.row.timestamp || ""}${p.row.prediction === 1 ? " · إشارة شذوذ" : ""}`)}</title></circle>`).join("");
		return {
			svg: `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc$3(`قراءات ${channel.name}، ${finite.length} قراءة متوفرة من ${rows.length}؛ الأقل ${number$1(rawMin)} والأعلى ${number$1(rawMax)}.`)}" xmlns="http://www.w3.org/2000/svg">${grid}<path class="chart-line" d="${path}"/>${dots}${labels}</svg>`,
			finiteCount: finite.length,
			missingCount: rows.length - finite.length,
			min: rawMin,
			max: rawMax,
			latest: finite.at(-1).value
		};
	}
	//#endregion
	//#region mawrid-system/client/plant.js
	var esc$2 = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		"\"": "&quot;",
		"'": "&#39;"
	})[c]);
	var finite$3 = (value) => typeof value === "number" && Number.isFinite(value);
	var number = (value, digits = 1) => finite$3(value) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value) : "—";
	var unit = (value, label, digits = 1) => `<bdi>${number(value, digits)}</bdi> <small>${esc$2(label)}</small>`;
	var icon$2 = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
	var clock = (value) => typeof value === "string" ? value.replace("T", " ").replace(/\.\d+(?=Z|[+-]\d\d:|$)/, "").replace(/Z$/, " UTC") : "—";
	var PLANT_MODES = {
		auto: "تشغيل تلقائي",
		standby: "استعداد",
		backwash: "غسيل عكسي"
	};
	var PLANT_FAULTS = {
		none: "تشغيل اعتيادي",
		turbidity: "ارتفاع العكارة",
		sensor_dropout: "انقطاع قراءة حساس",
		clogging: "انسداد المرشح",
		power_loss: "انقطاع الكهرباء",
		valve_stuck: "تعطل صمام الري"
	};
	var EQUIPMENT = {
		collection: {
			name: "خزان التجميع",
			tag: "TK-101",
			description: "يستقبل مياه الاستخدام ويوازن التدفق الداخل إلى خط المعالجة."
		},
		pump: {
			name: "مضخة التغذية",
			tag: "P-101",
			description: "تنقل المياه من خزان التجميع إلى وحدات الترشيح حسب وضع العملية."
		},
		media: {
			name: "مرشح الوسائط",
			tag: "F-101",
			description: "مرحلة إزالة العوالق. فرق الضغط يساعد على متابعة مقاومة المرشح والحاجة للغسيل."
		},
		carbon: {
			name: "مرشح الكربون",
			tag: "F-102",
			description: "مرحلة الكربون ضمن سلسلة المعالجة الافتراضية."
		},
		disinfection: {
			name: "وحدة التعقيم",
			tag: "D-101",
			description: "مرحلة الجرعات الافتراضية قبل خزان المياه المعالجة؛ الحالة المعروضة لمضخات الجرعات."
		},
		treated: {
			name: "خزان المياه المعالجة",
			tag: "TK-102",
			description: "يخزن الماء الخارج من المعالجة قبل قرار توجيهه إلى الري أو الصرف."
		},
		irrigation: {
			name: "صمام الري الافتراضي",
			tag: "XV-201",
			description: "يُتاح المسار وفق قواعد التوأم الرقمي. الحجم المعروض ناتج المحاكاة، وليس وفرًا مائيًا ميدانيًا."
		},
		drain: {
			name: "مسار الصرف",
			tag: "XV-202",
			description: "مسار التحويل أو التصريف داخل المحاكاة عند الحاجة التشغيلية."
		}
	};
	var statusNames = {
		running: "يعمل",
		on: "يعمل",
		off: "متوقف",
		stopped: "متوقف",
		open: "مفتوح",
		closed: "مغلق",
		ready: "جاهز",
		normal: "اعتيادي",
		fault: "عطل",
		blocked: "محجوز",
		warning: "تنبيه",
		backwash: "غسيل",
		standby: "استعداد",
		unavailable: "غير متاح"
	};
	var statusText = (value) => statusNames[value] || value || "غير متاح";
	var statusTone = (value) => [
		"fault",
		"blocked",
		"failed",
		"stuck"
	].includes(value) ? "danger" : [
		"running",
		"on",
		"open",
		"ready",
		"normal"
	].includes(value) ? "good" : value === "warning" ? "warning" : "neutral";
	var badge = (label, tone = "neutral") => `<span class="plant-chip ${tone}"><i></i>${esc$2(label)}</span>`;
	var field = (name, value) => `<div><dt>${esc$2(name)}</dt><dd>${value}</dd></div>`;
	function plantView(data) {
		const p = data?.virtual_plant, s = data?.session;
		if (data?.source?.kind !== "digital_twin" || data?.source?.id !== "virtual_plant" || !s?.id || !p || p.session_id !== s.id) return {
			active: false,
			sessionId: null
		};
		const ch = p.chans || {}, e = p.equipment || {}, f = p.flow || {}, tanks = p.tanks || {};
		const pressure = (a, b) => finite$3(ch[a]) && finite$3(ch[b]) ? ch[a] - ch[b] : null;
		const tank = (t) => t ? {
			liters: t.liters,
			capacity_liters: t.capacity_liters,
			level_pct: t.level_percent,
			status: "مخزون محاكى"
		} : void 0;
		const through = finite$3(f.treatment_lpm) && f.treatment_lpm > 0 ? "running" : "stopped";
		return {
			active: true,
			sessionId: s.id,
			running: p.running === true,
			simulation_timestamp: p.timestamp,
			mode: p.mode,
			fault: p.fault,
			speed: p.speed,
			safety_state: p.safety?.state,
			process_state: {
				REUSE: "معالجة وري",
				HOLD: "احتجاز",
				STANDBY: "استعداد",
				BACKWASH: "غسيل عكسي"
			}[p.safety?.state] || p.safety?.state,
			tanks: {
				collection: tank(tanks.raw),
				treated: tank(tanks.treated)
			},
			treatment_flow_lpm: f.treatment_lpm,
			inlet_flow_lpm: f.inlet_lpm,
			irrigation_flow_lpm: f.reuse_lpm,
			drain_flow_lpm: finite$3(f.drain_lpm) && finite$3(f.backwash_lpm) ? f.drain_lpm + f.backwash_lpm : null,
			reject_flow_lpm: f.drain_lpm,
			backwash_flow_lpm: f.backwash_lpm,
			irrigation_liters: p.volumes?.reuse_liters,
			filter_delta_pressure_bar: pressure("p1_bar", "p2_bar"),
			carbon_delta_pressure_bar: pressure("p2_bar", "p3_bar"),
			equipment: {
				pump: { status: e.feed_pump },
				media: { status: p.fault === "clogging" ? "warning" : through },
				carbon: { status: through },
				disinfection: { status: e.dosing_pumps },
				irrigation: { status: e.irrigation_valve },
				drain: { status: e.drain_valve }
			},
			readings: {
				outlet_turbidity: p.validity?.turbidity === false ? null : ch.turbidity,
				chlorine: p.validity?.chlorine === false ? null : ch.chlorine,
				ph: p.validity?.ph === false ? null : ch.ph
			},
			reasons: p.safety?.reasons || [],
			events: (data.alarms || []).filter((event) => event.session_id === s.id)
		};
	}
	function metric(title, value, note, name) {
		return `<article class="plant-metric"><span class="plant-metric-icon">${icon$2(name)}</span><div><p>${esc$2(title)}</p><strong>${value}</strong><small>${esc$2(note)}</small></div></article>`;
	}
	function metrics(v) {
		return metric("تدفق المعالجة", unit(v.treatment_flow_lpm, "L/min"), "التدفق الحالي في الخط", "wave") + metric("الري المحاكى", unit(v.irrigation_liters, "L"), "إجمالي هذه الجلسة الافتراضية", "droplet") + metric("فرق ضغط المرشح", unit(v.filter_delta_pressure_bar, "bar", 2), "عبر مرشح الوسائط", "settings") + metric("وضع العملية", `<span class="plant-mode-value">${esc$2(v.process_state || PLANT_MODES[v.mode] || "غير متاح")}</span>`, "من متحكم المحاكاة", "shield");
	}
	function selected(id, ui) {
		return ui.equipment === id ? " selected" : "";
	}
	function equipmentOpen(id, ui) {
		return `<g class="plant-equipment${selected(id, ui)}" data-equipment="${id}" tabindex="0" role="button" aria-label="تفاصيل ${EQUIPMENT[id].name}" aria-pressed="${ui.equipment === id}">`;
	}
	function svgLabel(x, y, id, status) {
		return `<text class="plant-svg-tag" x="${x}" y="${y}" text-anchor="middle">${EQUIPMENT[id].tag}</text><text class="plant-svg-name" x="${x}" y="${y + 23}" text-anchor="middle">${EQUIPMENT[id].name}</text><text class="plant-svg-status ${statusTone(status)}" x="${x}" y="${y + 42}" text-anchor="middle">${esc$2(statusText(status))}</text>`;
	}
	function tank(id, x, v, ui) {
		const t = v.tanks?.[id] || {}, pct = finite$3(t.level_pct) ? Math.max(0, Math.min(100, t.level_pct)) : null;
		const h = pct === null ? 0 : 120 * pct / 100, y = 295 - h;
		const previous = ui.previousLevels?.[id], from = finite$3(previous) ? 120 * Math.max(0, Math.min(100, previous)) / 100 : h;
		return `${equipmentOpen(id, ui)}<rect class="equipment-hit" x="${x - 18}" y="92" width="148" height="270" rx="14"/><rect class="tank-shell" x="${x}" y="157" width="112" height="150" rx="11"/><rect class="tank-inner" x="${x + 8}" y="165" width="96" height="134" rx="7"/><rect class="tank-water" x="${x + 9}" y="${y}" width="94" height="${h}" rx="4">${from !== h && !ui.reducedMotion ? `<animate attributeName="height" from="${from}" to="${h}" dur="0.45s" fill="freeze"/><animate attributeName="y" from="${295 - from}" to="${y}" dur="0.45s" fill="freeze"/>` : ""}</rect><path class="tank-scale" d="M${x + 90} 180h13m-13 23h13m-13 23h13m-13 23h13m-13 23h13"/><ellipse class="tank-cap" cx="${x + 56}" cy="157" rx="56" ry="13"/><path class="equipment-foot" d="M${x + 20} 308v13h-9m81-13v13h9"/><text class="tank-percent" x="${x + 50}" y="237" text-anchor="middle">${pct === null ? "—" : number(pct, 0) + "%"}</text><text class="tank-liters" x="${x + 56}" y="283" text-anchor="middle">${number(t.liters, 0)} L</text>${svgLabel(x + 56, 88, id, t.status)}</g>`;
	}
	function filter(id, x, v, ui) {
		const s = v.equipment?.[id]?.status;
		return `${equipmentOpen(id, ui)}<rect class="equipment-hit" x="${x - 17}" y="103" width="116" height="220" rx="13"/><rect class="filter-shell" x="${x}" y="189" width="82" height="97" rx="15"/><ellipse class="filter-top" cx="${x + 41}" cy="189" rx="41" ry="11"/><path class="filter-band" d="M${x + 2} 215h78m-78 45h78"/><rect class="filter-media ${id === "carbon" ? "carbon" : ""}" x="${x + 10}" y="222" width="62" height="31" rx="3"/><path class="equipment-foot" d="M${x + 15} 285v25h-9m61-25v25h9"/>${svgLabel(x + 41, 125, id, s)}</g>`;
	}
	function pipe(d, flow, extra = "") {
		return `<path class="plant-pipe-base ${extra}" d="${d}"/><path class="plant-pipe ${finite$3(flow) && flow > 0 ? "flowing" : ""} ${extra}" d="${d}"/>`;
	}
	function diagram(v, ui) {
		const eq = v.equipment || {}, flow = v.running ? v.treatment_flow_lpm : null;
		return `<svg class="plant-process-svg" viewBox="0 0 1260 430" role="group" aria-label="خط المعالجة؛ اختر جهازًا لعرض تفاصيله"><defs><linearGradient id="tank-steel" x1="0" x2="1"><stop offset="0" stop-color="#eef1e9"/><stop offset=".45" stop-color="#fffefa"/><stop offset="1" stop-color="#e2e9dd"/></linearGradient><linearGradient id="tank-water" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#94b9a1"/><stop offset="1" stop-color="#548b71"/></linearGradient></defs>
    <path class="plant-floor" d="M24 335H1236"/><text class="plant-line-label" x="1170" y="67" text-anchor="middle">مياه الاستخدام</text>${pipe("M1170 78V150", v.running ? v.inlet_flow_lpm : null)}
    ${pipe("M1090 252H990", flow)}${pipe("M932 252H845", flow)}${pipe("M763 252H684", flow)}${pipe("M602 252H537", flow)}${pipe("M421 252H337", flow)}
    ${pipe("M225 237H121V178H72", v.running ? v.irrigation_flow_lpm : null)}${pipe("M742 252V329H72", v.running ? v.drain_flow_lpm : null, "drain-pipe")}
    ${pipe("M281 307V414H804V286", v.running ? v.backwash_flow_lpm : null, "backwash-pipe")}
    <text class="plant-line-label" x="545" y="427" text-anchor="middle">خط الغسيل العكسي</text>
    <path class="pipe-direction" d="m1023 247-8 5 8 5m-125-10-8 5 8 5m-185-10-8 5 8 5m-159-10-8 5 8 5m-175-10-8 5 8 5"/>
    ${tank("collection", 1090, v, ui)}${tank("treated", 225, v, ui)}
    ${equipmentOpen("pump", ui)}<rect class="equipment-hit" x="915" y="104" width="94" height="219" rx="13"/><path class="pump-base" d="M931 288h61v17h-61Z"/><circle class="pump-body" cx="962" cy="252" r="32"/><g class="pump-rotor ${v.running && ["running", "on"].includes(eq.pump?.status) ? "running" : ""}" style="transform-origin:962px 252px"><path d="M962 252c-24-13-22-26-7-26l7 26c15-22 28-19 25-4l-25 4c9 26-1 34-12 24Z"/></g>${svgLabel(962, 125, "pump", eq.pump?.status)}</g>
    ${filter("media", 763, v, ui)}${filter("carbon", 602, v, ui)}
    ${equipmentOpen("disinfection", ui)}<rect class="equipment-hit" x="402" y="104" width="151" height="219" rx="13"/><rect class="uv-shell" x="421" y="230" width="116" height="45" rx="20"/><rect class="uv-lamp ${["running", "on"].includes(eq.disinfection?.status) ? "on" : ""}" x="436" y="248" width="86" height="8" rx="4"/><path class="equipment-foot" d="M443 275v28m72-28v28"/>${svgLabel(479, 125, "disinfection", eq.disinfection?.status)}</g>
    ${equipmentOpen("irrigation", ui)}<rect class="equipment-hit" x="14" y="111" width="135" height="111" rx="13"/><path class="valve-symbol ${eq.irrigation?.status === "open" ? "open" : ""}" d="m67 167 20 11-20 11Zm40 0-20 11 20 11ZM87 177v-22m-10 0h20"/><text class="outlet-name" x="78" y="137" text-anchor="middle">الري</text><text class="plant-svg-status ${statusTone(eq.irrigation?.status)}" x="78" y="211" text-anchor="middle">${esc$2(statusText(eq.irrigation?.status))}</text></g>
    ${equipmentOpen("drain", ui)}<rect class="equipment-hit" x="14" y="276" width="135" height="115" rx="13"/><path class="valve-symbol ${eq.drain?.status === "open" ? "open" : ""}" d="m67 318 20 11-20 11Zm40 0-20 11 20 11ZM87 328v-22m-10 0h20"/><text class="outlet-name" x="78" y="296" text-anchor="middle">الصرف</text><text class="plant-svg-status ${statusTone(eq.drain?.status)}" x="78" y="370" text-anchor="middle">${esc$2(statusText(eq.drain?.status))}</text></g>
    <g class="instrument"><rect x="1025" y="349" width="185" height="50" rx="7"/><text x="1197" y="369" text-anchor="end">تدفق التجميع</text><text class="instrument-value" x="1038" y="391">${number(v.inlet_flow_lpm, 1)} L/min</text></g>
    <g class="instrument"><rect x="738" y="349" width="153" height="50" rx="7"/><text x="878" y="369" text-anchor="end">فرق الضغط</text><text class="instrument-value" x="751" y="391">${number(v.filter_delta_pressure_bar, 2)} bar</text></g>
    <g class="instrument"><rect x="405" y="349" width="180" height="50" rx="7"/><text x="572" y="369" text-anchor="end">عكارة بعد المعالجة</text><text class="instrument-value" x="418" y="391">${number(v.readings?.outlet_turbidity, 2)} NTU</text></g>
    <g class="instrument"><rect x="199" y="349" width="172" height="50" rx="7"/><text x="358" y="369" text-anchor="end">الكلور المتبقي</text><text class="instrument-value" x="212" y="391">${number(v.readings?.chlorine, 2)} mg/L</text></g>
  </svg>`;
	}
	function details(v, ui) {
		const id = Object.hasOwn(EQUIPMENT, ui.equipment) ? ui.equipment : "collection", e = EQUIPMENT[id], t = v.tanks?.[id], status = t?.status || v.equipment?.[id]?.status;
		let rows = field("حالة الجهاز", badge(statusText(status), statusTone(status)));
		if (t) rows += field("المستوى", unit(t.level_pct, "%")) + field("الحجم الحالي", unit(t.liters, "L")) + field("سعة الخزان", unit(t.capacity_liters, "L", 0));
		if (id === "pump") rows += field("تدفق المعالجة", unit(v.treatment_flow_lpm, "L/min"));
		if (id === "media") rows += field("فرق الضغط", unit(v.filter_delta_pressure_bar, "bar", 2));
		if (id === "carbon") rows += field("فرق الضغط", unit(v.carbon_delta_pressure_bar, "bar", 2));
		if (id === "disinfection") rows += field("الكلور المتبقي", unit(v.readings?.chlorine, "mg/L", 2));
		if (id === "irrigation") rows += field("التدفق الحالي", unit(v.irrigation_flow_lpm, "L/min")) + field("حجم الري المحاكى", unit(v.irrigation_liters, "L"));
		if (id === "drain") rows += field("إجمالي التصريف", unit(v.drain_flow_lpm, "L/min")) + field("رفض المعالجة", unit(v.reject_flow_lpm, "L/min")) + field("الغسيل العكسي", unit(v.backwash_flow_lpm, "L/min"));
		return `<div class="plant-detail-heading"><span class="plant-tag">${e.tag}</span>${badge(statusText(status), statusTone(status))}</div><h3>${e.name}</h3><p>${e.description}</p><dl class="plant-detail-values">${rows}</dl><small class="plant-detail-note">${v.active ? "الحالة من محرك التوأم الرقمي." : "تظهر الحالة عند تشغيل المنشأة الافتراضية."}</small>`;
	}
	function events$1(v) {
		const rows = Array.isArray(v.events) ? v.events.slice(0, 6) : [];
		return rows.length ? rows.map((event) => `<article class="plant-event"><span class="plant-event-dot ${esc$2(["critical", "warning"].includes(event.severity) ? event.severity : "info")}"></span><div><strong>${esc$2(event.title || event.message || "حدث تشغيل")}</strong><p>${esc$2(event.detail || "")}</p></div><div class="plant-event-actions"><time dir="ltr">${esc$2(clock(event.timestamp))}</time>${Number.isSafeInteger(event.id) && !event.acknowledged_at ? `<button class="text-button" data-action="ack" data-id="${event.id}" data-mutation>تم الاطلاع ${icon$2("check")}</button>` : event.acknowledged_at ? "<small>تم الاطلاع</small>" : ""}</div></article>`).join("") : "<div class=\"plant-events-empty\">لا أحداث تشغيل مسجلة لهذه الجلسة.</div>";
	}
	function plantRegions(data, ui = { equipment: "collection" }) {
		const v = plantView(data);
		return {
			kpis: metrics(v),
			diagram: diagram(v, ui),
			detail: details(v, ui),
			events: events$1(v),
			process: `${badge(v.process_state || PLANT_MODES[v.mode] || "بانتظار التشغيل", {
				REUSE: "good",
				HOLD: "danger",
				BACKWASH: "warning",
				STANDBY: "neutral"
			}[v.safety_state] || "neutral")}<span class="plant-clock">${v.active && !v.running ? "المحاكاة متوقفة مؤقتًا · " : ""}ساعة المحاكاة <bdi>${esc$2(clock(v.simulation_timestamp))}</bdi></span><a class="button small" href="/plant3d/index.html" target="_blank" rel="noopener">عرض المنشأة 3D</a>`,
			reasons: Array.isArray(v.reasons) && v.reasons.length ? `<div class="plant-reasons">${icon$2("info")}<span>${v.reasons.map(esc$2).join(" · ")}</span></div>` : ""
		};
	}
	function plantPage(data, ui = { equipment: "collection" }, disabled = false) {
		const v = plantView(data), r = plantRegions(data, ui);
		const select = (id, title, options, value) => `<label class="plant-select"><span>${title}</span><select id="${id}" data-plant-control ${disabled || !v.active ? "disabled" : ""}>${Object.entries(options).map(([key, label]) => `<option value="${key}" ${String(value) === key ? "selected" : ""}>${label}</option>`).join("")}</select></label>`;
		return `<div id="plant-screen" data-session="${esc$2(v.sessionId || "")}" class="${v.active ? "plant-active" : "plant-idle"}${ui.zoom ? " plant-zoomed" : ""}"><div class="plant-context"><span class="plant-identity"><i></i>توأم رقمي · منشأة افتراضية</span><div data-plant-region="process">${r.process}</div></div>${!v.active ? `<section class="plant-start"><div><span>وحدة مورد / خط المعالجة 01</span><h2>المنشأة جاهزة للتشغيل الافتراضي</h2><p>ابدأ الجلسة لتتابع توازن الخزانات ومسار المعالجة، ثم اختبر استجابة الوحدة لسيناريوهات الأعطال.</p></div><button class="button primary" data-action="plant-start" data-mutation ${disabled ? "disabled" : ""}>${icon$2("play")}تشغيل المنشأة الافتراضية</button></section>` : ""}
    <div class="plant-kpis" data-plant-region="kpis">${r.kpis}</div>
    <section class="plant-process-panel"><div class="plant-process-heading"><div><span class="plant-section-code">PROCESS / 01</span><h2>مسار المياه داخل مورد</h2></div><div class="plant-legend"><span><i class="legend-flow"></i>معالجة</span><span><i class="legend-drain"></i>تصريف</span><span>اضغط الجهاز لتفاصيله</span><button class="button small plant-zoom-button" data-action="plant-zoom" aria-pressed="${Boolean(ui.zoom)}">${ui.zoom ? "عرض المسار كاملًا" : "تكبير المخطط"}</button></div></div><div class="plant-diagram-scroll" data-plant-region="diagram">${r.diagram}</div><div class="plant-equipment-tabs" aria-label="تفاصيل معدات المنشأة">${Object.entries(EQUIPMENT).map(([id, e]) => `<button type="button" data-equipment="${id}" aria-pressed="${ui.equipment === id}">${e.name}</button>`).join("")}</div><div data-plant-region="reasons">${r.reasons}</div>
    <div class="plant-controls">${select("plant-mode", "وضع التشغيل", PLANT_MODES, v.mode)}${select("plant-fault", "سيناريو الاختبار", PLANT_FAULTS, v.fault)}<div class="plant-speed"><span>سرعة المحاكاة</span><div>${[
			1,
			10,
			30
		].map((speed) => `<button type="button" data-action="plant-speed" data-plant-control data-speed="${speed}" aria-pressed="${v.speed === speed}" ${disabled || !v.active ? "disabled" : ""}><bdi>×${speed}</bdi></button>`).join("")}</div></div><button class="button small" data-action="plant-running" data-plant-control ${disabled || !v.active ? "disabled" : ""}>${icon$2(v.running ? "pause" : "play")}${v.running ? "إيقاف المحاكاة مؤقتًا" : "متابعة المحاكاة"}</button><a class="plant-lab-link" href="#model">${icon$2("brain")}مختبر الذكاء ${icon$2("arrow")}</a></div></section>
    <div class="plant-bottom"><section class="plant-events-panel"><div class="plant-process-heading"><div><span class="plant-section-code">OPERATION LOG</span><h2>أحداث التشغيل</h2></div><a class="text-button" href="#alerts">التنبيهات ${icon$2("arrow")}</a></div><div data-plant-region="events">${r.events}</div></section><section class="plant-detail-panel" data-plant-region="detail" aria-live="polite">${r.detail}</section></div><p class="plant-footnote">${icon$2("shield")}حماية التوأم بقواعد تشغيل، والنموذج البحثي في مختبر الذكاء.</p></div>`;
	}
	function updatePlant(container, data, ui, disabled = false) {
		const v = plantView(data), screen = container.querySelector("#plant-screen");
		if (!screen || screen.dataset.session !== (v.sessionId || "")) {
			container.innerHTML = plantPage(data, ui, disabled);
			return;
		}
		screen.classList?.toggle("plant-zoomed", Boolean(ui.zoom));
		const zoom = container.querySelector("[data-action=\"plant-zoom\"]");
		if (zoom) {
			zoom.textContent = ui.zoom ? "عرض المسار كاملًا" : "تكبير المخطط";
			zoom.setAttribute("aria-pressed", String(Boolean(ui.zoom)));
		}
		for (const button of container.querySelectorAll(".plant-equipment-tabs [data-equipment]")) button.setAttribute("aria-pressed", String(button.dataset.equipment === ui.equipment));
		const r = plantRegions(data, ui);
		const focusedEquipment = document.activeElement?.dataset?.equipment;
		for (const [key, html] of Object.entries(r)) {
			const node = container.querySelector(`[data-plant-region="${key}"]`);
			if (node && node.plantMarkup !== html) {
				node.innerHTML = html;
				node.plantMarkup = html;
			}
		}
		if (Object.hasOwn(EQUIPMENT, focusedEquipment)) container.querySelector(`[data-equipment="${focusedEquipment}"]`)?.focus({ preventScroll: true });
		for (const [id, key] of [["plant-mode", "mode"], ["plant-fault", "fault"]]) {
			const input = container.querySelector(`#${id}`);
			if (input) {
				if (input !== document.activeElement) input.value = v[key] ?? "";
				input.disabled = disabled || !v.active;
			}
		}
		for (const button of container.querySelectorAll("[data-action=\"plant-speed\"]")) {
			button.disabled = disabled || !v.active;
			button.setAttribute("aria-pressed", String(v.speed === Number(button.dataset.speed)));
		}
		const running = container.querySelector("[data-action=\"plant-running\"]");
		if (running) {
			running.disabled = disabled || !v.active;
			running.innerHTML = `${icon$2(v.running ? "pause" : "play")}${v.running ? "إيقاف المحاكاة مؤقتًا" : "متابعة المحاكاة"}`;
		}
	}
	//#endregion
	//#region mawrid-system/client/guide-content.js
	var guideContent = {
		identity: {
			name: "مورد",
			tagline: "لا لتر بلا تحقق",
			purpose: "يستهدف مورد إعادة استخدام مياه الوضوء والمغاسل في المرافق الكبيرة لري المسطحات، مع متابعة القراءات والقرارات وتوثيقها.",
			products: ["وحدة مورد: تصور لمحطة معالجة متكاملة مع طبقة متابعة وتحكم.", "صندوق مورد: تصور لإضافة طبقة المتابعة والتحقق إلى محطة قائمة، دون استبدال خط معالجتها."],
			stage: "المتاح الآن تجربة برمجية محلية وتوأم افتراضي ومختبر ذكاء بحثي. «لا لتر بلا تحقق» مبدأ التصميم؛ ليس ادعاءً بضمان جودة ماء جرى اختباره ميدانيًا."
		},
		components: [
			{
				id: "source",
				title: "مياه الوضوء والمغاسل",
				role: "مصدر المياه الذي يستهدفه مورد لإعادة الاستخدام في ري المسطحات.",
				benefit: "يبدأ فهم المعالجة بمعرفة مصدر الماء قبل دخوله إلى المحطة.",
				how: "يجمع التصور مياه الوضوء والمغاسل في مسار منفصل عن مياه المراحيض وحوض المطبخ وغسالة الصحون، ثم يمررها إلى المصفاة وخزان التجميع.",
				simulated: "يمثل التوأم مصدرًا افتراضيًا لهذه المياه؛ لا يستقبل مياهًا من مبنى فعلي.",
				limitation: "فصل المسارات جزء من التصميم المطلوب في الموقع، ولا يستطيع العرض إثباته أو إثبات صلاحية الماء الداخل."
			},
			{
				id: "inlet",
				title: "مدخل المياه",
				role: "بداية مسار المياه نحو خزان التجميع.",
				benefit: "يوضح كمية الماء الداخلة ويساعد على تتبعها حتى التخزين أو الري أو الصرف.",
				how: "تدخل المياه إلى خزان التجميع، ثم تسحبها مضخة التغذية إلى خط المعالجة.",
				simulated: "يحسب التوأم تدفق الدخول وحجمه المتراكم؛ لا يستقبل ماءً من موقع فعلي.",
				limitation: "اختيار مصدر المياه وفصله عن المصادر غير المناسبة يحتاج تصميمًا وفحصًا في الموقع."
			},
			{
				id: "strainer",
				title: "المصفاة الأولية",
				role: "جزء مقترح لحجز الشعر والوبر والشوائب الكبيرة قبل الخزان والمضخة.",
				benefit: "تخفف وصول الأجسام الكبيرة إلى المعدات اللاحقة.",
				how: "تُجمع الشوائب في سلة قابلة للتنظيف ضمن التصميم المقترح.",
				simulated: "تظهر في مسار التصميم؛ لا يحسب التوأم تراكم الشوائب فيها.",
				limitation: "لا تمثل معالجة كاملة للمياه، ولا يثبت وجودها وحده إزالة الزيوت أو الملوثات الذائبة."
			},
			{
				id: "raw",
				title: "خزان التجميع الأرضي",
				role: "يجمع المياه قبل دخولها خط المعالجة.",
				benefit: "يفصل بين وصول المياه واستهلاك خط المعالجة، ويجعل المخزون ظاهرًا للمشغل.",
				how: "يرتفع المخزون مع الدخول وينخفض مع سحب مضخة التغذية، ويُحسب الفائض منفصلًا.",
				simulated: "يمثل التصميم خزانًا أرضيًا من الفايبر جلاس بسعة 5000 لتر؛ المستوى والحجم في العرض يأتيان من حسابات المحرك.",
				limitation: "السعة جزء من تصميم التجربة. لا تُحاكى جودة الماء داخل الخزان أو اختلاطه كيميائيًا."
			},
			{
				id: "feed",
				title: "مضخة التغذية",
				role: "مضخة غاطسة تنقل المياه من خزان التجميع إلى مراحل المعالجة.",
				benefit: "تجعل حركة الماء عبر الخط قابلة للمتابعة والتحكم.",
				how: "تعمل في وضع المعالجة المسموح وتتوقف عند الاحتجاز أو الاستعداد أو انقطاع الكهرباء الافتراضي.",
				simulated: "يعرض البرنامج حالة المضخة وتدفق تغذية المعالجة.",
				limitation: "لا تُحسب قدرة المحرك أو استهلاكه الكهربائي، ولا تمثل الحركة اختبارًا لمضخة حقيقية."
			},
			{
				id: "flow_meter",
				title: "عداد تدفق خط المعالجة",
				role: "يوضح كمية الماء المارة في خط المعالجة بعد مضخة التغذية.",
				benefit: "يساعد على التمييز بين تدفق المعالجة وتدفق الري الخارج من الخزان المعالج.",
				how: "يعرض التدفق اللحظي، ويمكن ربطه بعداد الحجم الذي مر في الخط خلال الجلسة.",
				simulated: "قراءة العداد مأخوذة من تدفق المعالجة الذي يحسبه محرك التوأم؛ لا يولد المشهد رقمًا مستقلًا.",
				limitation: "ليست قراءة من عداد ميداني، ولا تعني أن كل ماء مر في الخط خرج للري أو اجتاز اختبار جودة."
			},
			{
				id: "dose_pre",
				title: "جرعة الكلور الأولية",
				role: "وحدة إضافة مقترحة قبل مرشح الوسائط.",
				benefit: "يستهدف التصميم بها الأكسدة والحد من النمو الحيوي داخل مراحل المعالجة.",
				how: "تمثل مضخة حقن الهيبوكلوريت في بداية الخط؛ تحديد الإضافة يحتاج تحليل الماء واختبار المعالجة.",
				simulated: "تظهر الوحدة وحالة تشغيلها الافتراضية؛ لا تُحاكى التفاعلات الكيميائية أو كمية المادة المستهلكة.",
				limitation: "تشغيل رمز المضخة لا يثبت إزالة ملوث أو فعالية تعقيم، ولا يرسل أمرًا إلى مضخة جرعات حقيقية."
			},
			{
				id: "media",
				title: "مرشح الوسائط",
				role: "مرحلة مخصصة لالتقاط العوالق أثناء مرور الماء عبر وسط ترشيح.",
				benefit: "تخفف حمل العوالق على المراحل التالية في التصميم.",
				how: "تساعد مقارنة الضغط قبل المرشح وبعده على متابعة مقاومة مرور الماء والحاجة إلى الفحص أو الغسيل.",
				simulated: "يعرض التوأم فرق الضغط ويتيح تجربة سيناريو انسداد المرشح.",
				limitation: "فرق الضغط افتراضي؛ لا تُحسب كفاءة إزالة العوالق أو عمر الوسط أو موعد صيانة تنبؤي."
			},
			{
				id: "dose_dechlor",
				title: "جرعة إزالة الكلور",
				role: "وحدة مقترحة بعد مرشح الوسائط وقبل مرشح الكربون.",
				benefit: "تتيح معالجة الكلور المتبقي قبل وصول الماء إلى مرحلة الكربون في التصميم.",
				how: "تمثل حقن ميتابيسلفيت الصوديوم، مع نقطة متابعة ORP بعدها؛ اختيار الإضافة والتحقق منها عمل هندسي وتجريبي.",
				simulated: "تظهر مضخة الإضافة وحالتها؛ لا يحسب التوأم استهلاك الكلور أو المادة الكيميائية أو الأكسجين.",
				limitation: "لا توجد نتيجة تثبت إزالة الكلور. قراءة ORP وحدها ليست قياسًا مباشرًا لتركيز الكلور أو دليلًا كافيًا على اكتمال الإزالة."
			},
			{
				id: "orp",
				title: "قياس ORP بعد إزالة الكلور",
				role: "نقطة قياس جهد الأكسدة والاختزال بعد جرعة إزالة الكلور وقبل الكربون.",
				benefit: "توضح للمشغل مؤشرًا إضافيًا لمتابعة ظروف الماء في هذه النقطة.",
				how: "يعرض المؤشر جهد الأكسدة والاختزال بوحدة الملي فولت؛ تفسيره يحتاج معرفة الماء والقياسات المصاحبة.",
				simulated: "قيمة التوأم إشارة توضيحية محسوبة، وليست نتيجة تفاعل كيميائي أو قياسًا من قطب موصول.",
				limitation: "ORP لا يعادل تركيز الكلور، ولا يثبت وحده إزالة الكلور أو سلامة الماء أو صحة الجرعة."
			},
			{
				id: "carbon",
				title: "مرشح الكربون",
				role: "مرحلة مقترحة لامتزاز بعض المواد من الماء على سطح الكربون.",
				benefit: "تضيف مرحلة معالجة تختلف عن حجز العوالق بالترشيح.",
				how: "يمر الماء عبر وسط الكربون، وتُتابع حالته ضمن خط المعالجة.",
				simulated: "يعرض التوأم موقع المرشح وفرق الضغط المرتبط به.",
				limitation: "لا يُحاكى التشبع أو إزالة ملوث محدد، ولا توجد هنا نتيجة تثبت كفاءة الكربون الطبيعي."
			},
			{
				id: "pilot",
				title: "عمود تجربة بيوتشار النخيل",
				role: "مسار بحثي مستقبلي لمقارنة كربون من مخلفات النخيل بالكربون التجاري المرجعي.",
				benefit: "يتيح دراسة الاستفادة من مخلف زراعي محلي قبل الاعتماد على المادة في خط الخدمة.",
				how: "تُقارن عينات قبل الوسط وبعده وتُتابع النتائج أثناء تجربة مخصصة.",
				simulated: "يظهر في التصور كعمود بحثي؛ لا تدفق تجريبي أو نتائج معالجة محسوبة له.",
				limitation: "البيوتشار ليس أساس نجاح مورد الحالي. يبدأ التصور بالكربون التجاري، ولا يُستبدل قبل إثبات الأداء؛ لا توجد نتيجة ميدانية أو نسبة إزالة أو عمر خدمة مثبتة للبيوتشار ضمن التطبيق."
			},
			{
				id: "cartridge",
				title: "مرشح الخراطيش",
				role: "مرحلة إضافية مقترحة للترشيح بعد الوسائط والكربون.",
				benefit: "تلتقط جزءًا من الجسيمات المتبقية بحسب الخرطوشة المختارة.",
				how: "يمر الماء عبر خرطوشة تُفحص وتُستبدل عند الحاجة ضمن خطة الصيانة.",
				simulated: "يظهر في مسار المعالجة؛ لا يحسب التوأم كفاءة الخرطوشة أو تراكم المواد داخلها.",
				limitation: "لم يُختبر هنا مقاس الخرطوشة أو زمن استبدالها أو أثرها في جودة المنتج."
			},
			{
				id: "dose_ph",
				title: "جرعة معالجة الروائح أو ضبط pH",
				role: "وحدة إضافة مقترحة بعد مرشح الخراطيش وقبل الكلورة النهائية.",
				benefit: "تترك في التصميم وسيلة لمعالجة حاجة تظهرها تحاليل الماء، مثل ضبط الأس الهيدروجيني.",
				how: "يُحدد استخدام الوحدة والمادة المناسبة بعد التحليل، مع فحص توافقها مع المراحل اللاحقة؛ ليست وصفة كيميائية ثابتة في التطبيق.",
				simulated: "تظهر الوحدة وحالتها الافتراضية، دون حساب تغير pH أو إزالة الروائح أو استهلاك مادة.",
				limitation: "لم تُثبت الحاجة إلى هذه الإضافة أو فعاليتها في مياه مورد، ولا يقدم التطبيق جرعة أو مادة معتمدة للتشغيل الميداني."
			},
			{
				id: "dose_final",
				title: "جرعة الكلور النهائية",
				role: "وحدة إضافة مقترحة قبل لوحة تحليل المنتج والتخزين.",
				benefit: "تمثل مرحلة مخصصة للتعقيم النهائي في التصور الهندسي.",
				how: "يستهدف التصميم متابعة الكلور المتبقي بعد الإضافة؛ التحقق الفعلي يحتاج قياسًا وزمن تلامس واختبارًا مناسبًا.",
				simulated: "تظهر المضخة وحالتها الافتراضية؛ لا يحسب المحرك جرعة أو زمن تلامس أو خفضًا ميكروبيًا.",
				limitation: "وجود قراءة كلور افتراضية أو مضخة تعمل في الرسم لا يثبت تعقيم الماء أو صلاحيته للاستخدام."
			},
			{
				id: "quality",
				title: "لوحة تحليل جودة المنتج",
				role: "تجمع نقاط متابعة الماء بعد المعالجة وقبل صمام المطابقة وخزان المنتج.",
				benefit: "تجعل مؤشرات الماء قابلة للقراءة معًا بدل الاعتماد على مؤشر واحد.",
				how: "يتضمن التصور قياس العكارة والكلور الحر وpH والحرارة والموصلية، مع بقاء كل قراءة مرتبطة بمصدرها ووحدتها.",
				simulated: "يعرض التوأم إشاراته المتاحة فقط؛ الموصلية وغيرها من القياسات غير المنفذة تبقى غير متاحة.",
				limitation: "لوحة العرض ليست تحليلًا مخبريًا، ولا يُستنتج من لون المؤشرات أو قراءاتها الافتراضية أن المنتج صالح للري."
			},
			{
				id: "compliance",
				title: "صمام المطابقة وخط الإعادة",
				role: "جزء من التصميم المقترح لاختيار مسار الماء بعد المعالجة وقبل خزان المنتج.",
				benefit: "يوضح فكرة عزل المنتج وإعادة الماء للفحص أو المعالجة عند الحاجة.",
				how: "يرسم التصور الهندسي فرعًا يعيد الماء إلى خزان التجميع بدل دخوله إلى خزان المنتج.",
				simulated: "خط الإعادة ظاهر للتوضيح ولا يحمل تدفقًا محسوبًا؛ حالة الاحتجاز في المحرك توقف التدفقات.",
				limitation: "الرسم لا يثبت تحقق جودة الماء أو وجود تحويل ميداني عامل. صمام الري الافتراضي وحالته يعرضان بصورة مستقلة."
			},
			{
				id: "uv",
				title: "التعقيم بالأشعة فوق البنفسجية",
				role: "خيار مذكور في التصور الهندسي لمرحلة تعقيم إضافية.",
				benefit: "يتيح دراسة حاجز تعقيم إضافي عند إعداد التصميم الفعلي.",
				how: "يحتاج تشغيله الحقيقي إلى اختيار وحدة مناسبة ومراقبتها والتحقق من أدائها.",
				simulated: "يظهر موضع وحدة UV في التصميم، دون قراءة شدة أشعة أو محاكاة تعقيم.",
				limitation: "مؤشر تشغيل مضخات الجرعات لا يمثل شدة الأشعة أو إثبات التعقيم."
			},
			{
				id: "treated",
				title: "خزان المياه المعالجة الأفقي",
				role: "يستقبل المنتج بعد خط المعالجة، ثم يغذي مسار الري أو الغسيل.",
				benefit: "يفصل إنتاج الماء عن وقت استهلاكه ويُظهر المخزون المتاح.",
				how: "يزداد المخزون مع المنتج ويقل مع الري أو الغسيل العكسي، ويُسجل فائض الامتلاء منفصلًا.",
				simulated: "يمثل التصميم خزانًا أفقيًا من البولي إيثيلين بسعة 5000 لتر؛ يحسب المحرك حجمه ومستواه.",
				limitation: "اسم الخزان يصف موقعه في العملية؛ لا يمنح الماء شهادة صلاحية أو يثبت جودة معالجة فعلية."
			},
			{
				id: "reuse",
				title: "مضخة ومسار الري",
				role: "ينقلان الماء من الخزان المعالج إلى مخرج الاستخدام.",
				benefit: "يفصلان كمية المنتج عن كمية الماء التي خرجت للري بالفعل داخل المحاكاة.",
				how: "يحسب التوأم تدفق الري وحجمه المتراكم عندما تسمح قواعد التشغيل.",
				simulated: "العداد يعرض ريًا افتراضيًا محسوبًا، وليس قياسًا من مزرعة.",
				limitation: "لا يحسب البرنامج احتياج النبات، ولا تثبت هذه الكمية وفرًا ميدانيًا أو ملاءمة الماء لمحصول معين."
			},
			{
				id: "valve",
				title: "صمام الري",
				role: "يسمح بمرور الماء في مسار الري أو يعزله.",
				benefit: "يوضح الفرق بين طلب التشغيل وحالة الصمام التي يؤكدها النظام.",
				how: "في سيناريو تعطل الصمام قد يظهر طلب فتح مع تأكيد بقائه مغلقًا؛ يحتجز التوأم التدفق ويبيّن السبب.",
				simulated: "حالة الصمام والأمر والتأكيد جميعها افتراضية.",
				limitation: "لا يوجد صمام مادي موصول، ولا يفتح النموذج البحثي صمامًا. خط الإعادة إلى الخزان الخام جزء من التصور، ولا يحمل تدفقًا محسوبًا في النسخة الحالية."
			},
			{
				id: "backwash",
				title: "مضخة ومسار الغسيل العكسي",
				role: "مسار صيانة مخصص لغسل المرشحات.",
				benefit: "يفصل استهلاك ماء الغسيل عن ماء الري والمنتج.",
				how: "عند اختيار الغسيل العكسي يسحب التوأم الماء من الخزان المعالج إلى مصرف الغسيل، مع توقف المعالجة والري.",
				simulated: "يحسب المحرك حجم الغسيل ويوقف السحب عندما لا يتبقى مخزون.",
				limitation: "لا تُحاكى استعادة كفاءة المرشح بعد الغسيل؛ اختيار هذا الوضع لا يمسح سيناريو الانسداد تلقائيًا."
			},
			{
				id: "drain",
				title: "مسارات الصرف والفائض",
				role: "توضح أين يذهب الماء الذي لا يخرج للري أو يبقى في الخزانات.",
				benefit: "تمنع احتساب ماء الغسيل أو الفائض ضمن كمية إعادة الاستخدام.",
				how: "يسجل البرنامج ماء الغسيل العكسي وفائض الخزانات منفصلًا عن الري.",
				simulated: "التدفقات والأحجام جزء من ميزان الماء الافتراضي.",
				limitation: "هذا تتبع حسابي؛ لا يمثل تصميم صرف معتمدًا أو تصريحًا لتصريف مياه في الموقع."
			},
			{
				id: "sensors",
				title: "حساسات جودة المياه",
				role: "تعرض مؤشرات مثل العكارة والأس الهيدروجيني والكلور المتبقي وORP.",
				benefit: "تجعل التغير أو فقد القراءة ظاهرًا بدل الحكم على الماء من مظهره وحده.",
				how: "تظهر كل قراءة بوحدتها ومصدرها؛ القراءة المفقودة تبقى غير متاحة.",
				simulated: "قيم التوأم إشارات توضيحية محسوبة، أما مختبر الذكاء فيقرأ ملفات حساسات عامة منفصلة.",
				limitation: "ORP ليس قياسًا للكلور، وهذه المؤشرات لا تغني عن التحليل المخبري. حساسات الملوحة وUV254 وغيرها في التصور ليست قراءات حية منفذة هنا."
			},
			{
				id: "pressure",
				title: "قياس الضغط وفرق الضغط",
				role: "يتابع الضغط في نقاط خط المعالجة ومقدار تغيره عبر المرشحات.",
				benefit: "يساعد المشغل على فهم مقاومة الخط وملاحظة أثر سيناريو الانسداد.",
				how: "تعرض الشاشة قراءات الضغط وفرق الضغط عند المعدات المرتبطة بها.",
				simulated: "تتغير الإشارات وفق وضع التشغيل والسيناريو المختار.",
				limitation: "ليست قياسات من أنابيب فعلية أو حسابات هيدروليكية معايرة، ولا تثبت وحدها سبب عطل في محطة حقيقية."
			},
			{
				id: "level-flow",
				title: "المستوى والتدفق والعدادات",
				role: "توضح مقدار الماء المخزن وسرعة انتقاله وحجمه المتراكم.",
				benefit: "تساعد على التمييز بين تدفق لحظي ومخزون حالي وكمية مرت خلال الجلسة.",
				how: "المستوى نسبة امتلاء، والتدفق باللتر في الدقيقة، والحجم المتراكم باللتر.",
				simulated: "كل هذه القيم مشتقة من حسابات محرك التوأم؛ عداد الري يتبع الخزان المعالج.",
				limitation: "التصميم بسعة 15 م³ يوميًا عند 15 ساعة تشغيل. نقل الحجم في التوأم لا يثبت إزالة الملوثات، وكمية الري المعروضة تخص الجلسة نفسها."
			},
			{
				id: "electrical",
				title: "التغذية ولوحة الكهرباء",
				role: "تمثل مصدر تشغيل المضخات ومعدات التحكم.",
				benefit: "توضح أثر فقد الكهرباء على المحطة بالكامل.",
				how: "عند تجربة انقطاع الكهرباء تتوقف المضخات والتدفقات وتغلق الصمامات الافتراضية.",
				simulated: "يحاكي البرنامج توفر التغذية أو فقدها فقط.",
				limitation: "لا توجد لوحة موصولة أو قياسات تيار وطاقة فعلية، ولا يمثل السيناريو اختبار حماية كهربائية."
			},
			{
				id: "panel",
				title: "لوحة التحكم PLC",
				role: "موضع تجميع إشارات الحساسات وأوامر المعدات في التصور الميداني.",
				benefit: "تربط القياسات بحالات التشغيل وتتيح متابعة سبب التوقف من نقطة واحدة.",
				how: "يوضح التصميم لوحة محلية للمضخات والجرعات والصمامات، مع فصل منطق التشغيل عن طبقة المتابعة البحثية.",
				simulated: "تظهر اللوحة في المشهد؛ تنفذ الخدمة المحلية قواعد التوأم، ولا تتصل بوحدة PLC مادية.",
				limitation: "لا يثبت هذا العرض اختبار لوحة كهربائية أو متحكم ميداني. النموذج البحثي لا يتحكم بمعدات التوأم أو بعتاد حقيقي."
			},
			{
				id: "dosing",
				title: "مضخات الجرعات والتعقيم",
				role: "تمثل معدات إضافة المواد اللازمة لخط المعالجة في التصميم.",
				benefit: "تتيح تنظيم الإضافة بدل الاعتماد على السكب اليدوي.",
				how: "يتضمن التصور الهندسي مراحل للكلورة وإزالة الكلور وضبط المعالجة؛ اختيار المواد وكمياتها يحتاج تصميمًا واختبارًا.",
				simulated: "تظهر أربع وحدات جرعات في التصميم، مرتبطة بحالة تشغيل خط المعالجة.",
				limitation: "لا يحسب البرنامج جرعة كيميائية أو زمن تلامس أو فعالية تعقيم، ولا يصدر أوامر إلى مضخات مادية."
			},
			{
				id: "controller",
				title: "منطق التشغيل والحماية",
				role: "يحدد حالة المعالجة أو الاحتجاز أو الاستعداد أو الغسيل داخل التوأم.",
				benefit: "يجعل سبب التوقف واضحًا ويمكن تكرار تجربته.",
				how: "يطبق المحرك قواعد ثابتة على حالة المعدات والقراءات، ويسجل سبب الاستجابة.",
				simulated: "القواعد تدير المنشأة الافتراضية؛ نموذج كشف الشذوذ منفصل عنها.",
				limitation: "ليس متحكم أمان ميدانيًا معتمدًا. حدود استقبال قراءات الجهاز لا تغيّر قواعد التوأم."
			},
			{
				id: "sampling",
				title: "نقاط العينات والفحص المخبري",
				role: "جزء من التصور الميداني للتحقق من الماء قبل المعالجة وبعدها.",
				benefit: "تربط الحكم على جودة الماء بأدلة قياس مستقلة.",
				how: "تُحدد نقاط أخذ العينات والفحوص ضمن خطة التجربة الميدانية.",
				simulated: "لا ينتج التطبيق تحليلًا مخبريًا أو نتيجة لعينات مورد.",
				limitation: "اللون الأخضر أو انخفاض العكارة في العرض لا يعوض اختبار جودة الماء."
			},
			{
				id: "collector",
				title: "جامع القراءات المحلي",
				role: "يستقبل ملفات قراءات ويحتفظ بها قبل إرسالها إلى التطبيق.",
				benefit: "يسمح بإعادة المحاولة عند انقطاع الإرسال مع تتبع كل قراءة وجلستها.",
				how: "تُحفظ القراءة بهوية ثابتة، ولا تُعد مستلمة حتى يصل إيصال مطابق من الخادم.",
				simulated: "برنامج نقل فعلي يعمل محليًا؛ يقبل قياسات يجهزها المستخدم أو ملفات اختبار موسومة.",
				limitation: "لا يتصل بحساس تلقائيًا ولا يولد قياسات. وصول الإيصال يثبت حفظ الرسالة فقط، والنموذج غير مؤهل لهذا المسار حاليًا."
			},
			{
				id: "screen",
				title: "الشاشة والسجل والعرض ثلاثي الأبعاد",
				role: "تجمع حالة التشغيل والقياسات والأحداث في واجهة واحدة.",
				benefit: "تساعد المشغل على فهم التسلسل ومراجعة ما حدث وتصدير السجل.",
				how: "تقرأ الشاشة والعرض التشغيلي ثلاثي الأبعاد الحالة نفسها من الخدمة المحلية؛ التحكم من غرفة التشغيل.",
				simulated: "المخطط والمجسم يعرضان التوأم الحالي، وتحفظ الجلسات السابقة مع مصدر كل قراءة.",
				limitation: "عرض المنشأة لا يشغل جلسة وحده. عند انقطاع الاتصال تتوقف الحركة وتظهر علامة الانقطاع بدل اختلاق حالة جديدة."
			},
			{
				id: "remote",
				title: "الاتصال والمتابعة عن بعد",
				role: "طبقة مستقبلية مقترحة لعرض حالة محطة ميدانية خارج موقعها.",
				benefit: "يمكن أن تساعد فريق التشغيل على متابعة المواقع عند تطوير الربط وتأهيله.",
				how: "تحتاج ربط أجهزة وصلاحيات اتصال وآلية تشغيل وصيانة مناسبة.",
				simulated: "التطبيق الحالي يعمل على هذا الجهاز؛ ليست هناك منصة سحابية أو وصلة ميدانية مفعلة.",
				limitation: "وجود شاشة أو جامع قراءات لا يعني اتصال محطة فعلية أو توفر خدمة متابعة سحابية."
			}
		],
		softwareSteps: [
			{
				title: "ابدأ المنشأة الافتراضية",
				text: "افتح «جرّب المحطة» واضغط «تشغيل المحطة». إذا وجدت جلسة متوقفة اضغط «متابعة التجربة». الزر التالي يتبع حالة المحطة الفعلية، ولا تبدأ الجلسة بمجرد فتح الصفحة."
			},
			{
				title: "اتبع مسار الماء",
				text: "تابع ثماني خطوات من التجميع إلى الري. في كل خطوة تُضاء المعدات ومسارها، وتظهر وظيفتها وفائدتها. اختر «ابدأ العرض التلقائي» لتتنقل الكاميرا مع مهلة قراءة لكل مرحلة، أو تابع يدويًا. «إيقاف العرض» يثبت الشرح؛ «إيقاف المحاكاة» يوقف زمن الماء. ينتهي العرض دون تفعيل عطل تلقائي."
			},
			{
				title: "اقرأ العدادات بمعناها",
				text: "افتح «التفاصيل» عندما تريد الأرقام. التدفق يصف سرعة انتقال الماء، وعداد اللترات يجمع ما مر خلال الجلسة. الأرقام افتراضية وليست وفرًا ميدانيًا مقاسًا؛ يمكنك فتح الحالة والسجل للمراجعة."
			},
			{
				title: "جرّب حالة واحدة",
				text: "في نهاية رحلة الماء يظهر «جرّب انقطاع الحساس». اقرأ سبب إغلاق الري ثم اضغط «إزالة العطل ومتابعة التشغيل». نتيجة العودة تعتمد على تأكيد المحرك. مدة كل خطوة في الشرح ليست زمن عبور الماء، والجرعات وفعالية المعالجة غير محسوبة."
			},
			{
				title: "غيّر الوضع والسرعة",
				text: "لمن يريد تجارب إضافية: افتح «التفاصيل» ثم «خيارات تشغيل إضافية». تجد السرعة والأعطال وأوضاع الاستعداد والغسيل. هذه خيارات تغيّر المحاكاة الحالية؛ التجربة الأساسية لا تحتاجها. الإيقاف المؤقت متاح أسفل المشهد."
			},
			{
				title: "ميّز التوقف المؤقت عن الاحتجاز",
				text: "«إيقاف المحاكاة مؤقتًا» يثبت الساعة والعدادات مع إبقاء آخر حالة معروضة. الاحتجاز اليدوي يطلب توقف العملية داخل التوأم؛ إزالة هذا الطلب لا تستأنف الساعة وحدها، ولا ترسل أمرًا إلى عتاد."
			},
			{
				title: "راجع ما حدث",
				text: "افتح التنبيهات وسجل الجلسة. «تم الاطلاع» يوثق مراجعتك ولا يعالج سبب العطل. يمكنك تصدير القراءات والأحداث؛ يبقى كل سجل مرتبطًا بمصدره حتى بعد بدء جلسة جديدة."
			},
			{
				title: "استكشف مختبر الذكاء بصورة منفصلة",
				text: "اختر مصدرًا عامًا في مختبر الذكاء واقرأ إقرار النطاق البحثي. كل خطوة تعيد قراءة تاريخية وتحسب نتيجتها فعليًا. هذا يغيّر مصدر الجلسة؛ لا يستخدم النموذج ماء التوأم ولا يتحكم بمعداته."
			},
			{
				title: "استقبل قراءات عند توفرها",
				text: "لمسار الجهاز، ابدأ جلسة استقبال قراءات وانسخ معرّفها من بطاقة الربط. استخدم جامع القراءات المحلي وفق دليله، ثم راجع اسم الجهاز ووقت الاستلام والإيصال. لا تسمِّ ملف اختبار قياسًا ميدانيًا؛ هذا المسار لا يفعّل النموذج البحثي."
			}
		],
		ai: {
			plain: "الذكاء الاصطناعي هنا تجربة لكشف أحداث غير معتادة في سلاسل قراءات الحساسات. يساعد على دراسة التنبيه عند تغير القراءات، ولا يقرر أن الماء آمن. حماية المنشأة الافتراضية تأتي من قواعد تشغيل منفصلة.",
			algorithm: "تستخدم سلسلة النماذج البحثية خوارزمية Isolation Forest لكشف الشذوذ، ونماذج أشجار معززة HGB تتعلم من أمثلة الأحداث والقراءات العادية. يُختبر قرار الإنذار على تسلسل زمني. الدرجة التي تظهر ترتيب بحثي، وليست نسبة ثقة في سلامة الماء.",
			data: "مصادر التطوير عامة: GECCO لقراءات جودة المياه، وWaterHub لقراءات ضغط شبكة مياه. ليست بيانات ميدانية من منشأة مورد أو من مياه الوضوء. قراءات التوأم الافتراضية لا تُخلط بهذه المصادر.",
			validation: [
				"يشمل التقييم المعلن 19 فترة زمنية. تُستخدم الفترات الماضية للتدريب والمعايرة، وتُختبر القرارات على فترات لاحقة مع حفظ هوية الأحداث والقراءات المفقودة.",
				"الفترات نفسها سبق الاطلاع عليها في تجارب التطوير؛ لذلك لا نصف النتائج بأنها تحقق خارجي جديد أو تجربة ميدانية مستقلة.",
				"انتهت تجربة V15 إلى قرارات V8 نفسها في الفترات كلها: كشف 117 من أصل 399 حدثًا، مع 235 مقطع إنذار كاذب بإجمالي 475 دقيقة. ليست هذه أرقام نسخة V9 المتصلة بالتطبيق.",
				"كشف 117 من 399 يعادل نحو 29.3% من الأحداث وفق تعريف الكشف في التقييم. هذا مقياس على مستوى الحدث؛ ولا يعني اكتشاف كل دقيقة داخل تلك الأحداث.",
				"بلغ F1 على القراءات المتاحة نحو 4.55%. يجمع هذا المقياس الدقة الإيجابية والاستدعاء على مستوى القراءات، وهو مختلف عن نسبة كشف الأحداث وعن Accuracy التي تحسب نسبة القرارات الصحيحة إجمالًا. لا يصح استبدال أحدها بالآخر أو إعلان «دقة 29.3%».",
				"مقطع الإنذار الكاذب فترة إنذار أثناء قراءات موسومة عادية؛ عدد المقاطع يصف تكرارها، ومجموع الدقائق يصف مدتها. تُراجع القيمتان مع الأحداث المفقودة والتأخير، وليس رقمًا واحدًا فقط.",
				"لم يتحقق هدف الاحتفاظ بكل الأحداث مع تقليل الإنذارات بصورة ثابتة: احتفظ V15 بـ117 من 119 حدثًا سبق كشفها باتحاد المرجعين V6 وV8. هذا الاتحاد مجموعة للمقارنة، وليس مقام نسبة الكشف الأصلي البالغ 399.",
				"اجتياز التدقيق الحسابي يعني مطابقة التنفيذ والحسابات ضمن نطاق الاختبار؛ لا يعني أن جودة النموذج حققت الهدف أو أن منظومة المياه معتمدة."
			],
			limits: [
				"لم يُثبت تصنيف أعطال الحساسات الخمسة أو الفصل الموثوق بين عطل حساس وحدث جودة حقيقي.",
				"لم تُثبت صلاحية مياه الوضوء لإعادة الاستخدام أو سلامة الماء من هذه التجارب.",
				"لا توجد نتيجة ميدانية من منشأة مورد أو قياسات وفر حقيقية في هذا التطبيق.",
				"لم يُقَس زمن الاستدلال على Raspberry Pi؛ تسريع العرض على هذا الجهاز ليس اختبارًا له.",
				"تأهيل إعادة العرض البرمجي محدود بمقاطع المصادر التي اختُبرت، ولا يثبت تطابق الاستدلال المتسلسل لكل الفترات أو لمصادر جديدة.",
				"التنبؤ بالطلب والمساعد العربي والتشخيص التنبؤي للصيانة ليست قدرات مثبتة ضمن النموذج المتصل حاليًا."
			],
			safety: "لا يفتح النموذج البحثي صمامًا ولا يمنح إذن استخدام للماء. لا يوجد عتاد موصول بهذا التطبيق. قواعد التوأم قد تفتح صمامه الافتراضي فقط، وعند الفقد أو الخلل تعرض سبب الاحتجاز. الحكم الميداني على الماء يحتاج تحققًا مستقلًا مناسبًا لمصدره واستخدامه.",
			versions: [
				"التوأم الرقمي: محاكاة تشغيل بقواعد ثابتة، دون استدلال من النموذج البحثي على مياهه.",
				"V9: النسخة المتصلة حاليًا بمختبر البيانات العامة. اكتشفت في تقييم التطوير 113 من 399 حدثًا، مع 237 مقطعًا كاذبًا و478 دقيقة كاذبة. اتصالها بالتطبيق لا يعني أنها أفضل النماذج أو أنها اجتازت هدف الجودة.",
				"تأهيل V9 البرمجي: تطابقت إعادة الحساب المتسلسلة مع المرجع في أول 1600 قراءة من مصدرين، على بيئة Mac الحالية. هذا تحقق من التنفيذ في نطاق محدد، وليس اعتمادًا ميدانيًا.",
				"V15: تجربة لسياسة الإنذار دون إعادة تدريب؛ لم تعتمد تعديلًا جديدًا وانتهت إلى V8 دون تغيير في الفترات الـ19. لم تُرقَّ إلى التطبيق.",
				"أي تجربة تطوير لاحقة تبقى منفصلة حتى تكتمل أدلتها ويُقرر ربطها صراحةً؛ لا توجد ترقية صامتة للنموذج."
			]
		},
		audiences: [
			"لمديري المرافق الكبيرة: استكشاف تصور وحدة مورد أو إضافة صندوق مورد إلى محطة قائمة؛ لا يفترض العرض وجود تركيب أو شراكة ميدانية منجزة.",
			"للمشغل: فهم مسار الماء، قراءة الحالات، تجربة الأعطال ومراجعة السجل.",
			"لفريق المشروع والمقيّمين: تجربة برمجية واضحة المصدر، مع فصل المنفذ حاليًا عن التصور الهندسي والبحث الجاري.",
			"لفريق الهندسة: مراجعة تسلسل المعدات والافتراضات قبل إعداد تصميم ميداني والتحقق منه.",
			"لفريق البيانات: مراجعة حدود التقييم وتكرار الإنذارات والأحداث المفقودة دون مساواة نجاح الحساب بنجاح النموذج."
		]
	};
	//#endregion
	//#region mawrid-system/client/water-journey.js
	var WATER_JOURNEY = [
		{
			id: "collection",
			short: "التجميع",
			title: "نجمع الماء قبل معالجته",
			role: "تصل مياه الوضوء والمغاسل عبر المصفاة إلى خزان التجميع، ثم تسحبها المضخة.",
			benefit: "حجز الشوائب الكبيرة وتوفير مخزون يغذّي خط المعالجة."
		},
		{
			id: "media",
			short: "مرشح الوسائط",
			title: "نحجز العوالق",
			role: "يمر الماء بنقطة الجرعة الأولية ثم مرشح الوسائط الذي يحجز العوالق.",
			benefit: "تخفيف حمل الجسيمات على المراحل التالية."
		},
		{
			id: "carbon",
			short: "مرشح الكربون",
			title: "يمر الماء عبر الكربون",
			role: "تسبق الكربون وحدة إزالة الكلور ونقطة متابعة، ثم يمر الماء عبر الكربون التجاري.",
			benefit: "إضافة معالجة لبعض المواد التي لا يحجزها الترشيح وحده."
		},
		{
			id: "polish",
			short: "الترشيح الدقيق",
			title: "نستكمل تجهيز الماء",
			role: "يعبر الماء مرشح الخراطيش، ثم نقطتي الإضافة لضبط الماء والكلورة النهائية.",
			benefit: "ترشيح إضافي وتجهيز الماء للفحص قبل التخزين."
		},
		{
			id: "verify",
			short: "التحقق",
			title: "نقرأ المؤشرات قبل التمرير",
			role: "تعرض لوحة التحليل مؤشرات الماء، ويحدد صمام المطابقة مساره في التصميم.",
			benefit: "ربط القياس بالقرار. عند الاحتجاز توقف المحاكاة التدفق؛ لا تحسب إعادة الماء للخام."
		},
		{
			id: "uv",
			short: "التعقيم الإضافي",
			title: "حاجز تعقيم إضافي اختياري",
			role: "يتضمن التصميم موضعًا للأشعة فوق البنفسجية قبل خزان المنتج.",
			benefit: "إضافة حاجز تعقيم محتمل؛ فعاليته تحتاج اختبارًا فعليًا."
		},
		{
			id: "storage",
			short: "خزان المنتج",
			title: "نخزن الماء بعد المعالجة",
			role: "يستقبل الخزان الأفقي الماء بعد خط المعالجة، ويظهر مخزونه في المحاكاة.",
			benefit: "فصل وقت إنتاج الماء عن وقت استخدامه للري."
		},
		{
			id: "irrigation",
			short: "الري",
			title: "نصل إلى الري",
			role: "تنقل المضخة الماء من الخزان إلى مسار الري عندما تسمح قواعد المحاكاة.",
			benefit: "قياس كمية الماء المتجهة للري ومتابعة مساره حتى الاستخدام."
		}
	];
	function journeyProgress(ui = {}, sessionId) {
		const same = typeof sessionId === "string" && ui.journeySession === sessionId;
		const index = same && Number.isInteger(ui.journeyIndex) ? Math.max(0, Math.min(WATER_JOURNEY.length - 1, ui.journeyIndex)) : 0;
		return {
			index,
			total: WATER_JOURNEY.length,
			stage: WATER_JOURNEY[index],
			complete: same && ui.journeyComplete === true
		};
	}
	//#endregion
	//#region mawrid-system/client/experience-state.js
	var finite$2 = (value) => typeof value === "number" && Number.isFinite(value);
	var result = (id, title, text, action, label, tone, step) => ({
		id,
		title,
		text,
		action,
		label,
		tone,
		step
	});
	var reason = (v) => Array.isArray(v.reasons) ? v.reasons.filter((x) => typeof x === "string" && x.trim()).join(" · ") : "";
	function experienceState(data, ui = {}, connected = false) {
		if (!data) return result("loading", "جارٍ الاتصال بالمحطة", "ننتظر حالة المحطة من الخدمة المحلية.", null, "", "idle", 0);
		if (!connected) return result("disconnected", "انقطع الاتصال", "المشهد يعرض آخر حالة مستلمة. انتظر عودة الاتصال قبل متابعة التجربة.", null, "", "warning", 0);
		const v = plantView(data), p = data.virtual_plant;
		const controllable = v.active && ["ready", "paused"].includes(data.session?.status);
		if (data.overview?.manual_hold === true || controllable && p?.manual_hold === true) return result("manual-hold", "الإيقاف اليدوي مفعّل", "ألغِ الطلب اليدوي أولًا. تبقى المحطة متوقفة حتى تضغط متابعة التجربة.", "release", "إلغاء الإيقاف اليدوي", "warning", 0);
		if (!controllable) return result("start", data.session?.status === "failed" && v.active ? "توقفت الجلسة بعد خطأ" : "شغّل محطة مورد", data.session?.status === "failed" && v.active ? "تحتاج المحاكاة إلى جلسة جديدة. يبقى سجل الجلسة السابقة محفوظًا." : "شاهد الماء يمر بالمعالجة ثم يتجه إلى الري داخل المحاكاة.", "start", "تشغيل المحطة", "idle", 0);
		if (typeof v.fault !== "string" || !v.fault || typeof v.mode !== "string" || !v.mode || typeof p.running !== "boolean") return result("unavailable", "حالة المحطة غير مكتملة", "ننتظر حالة تشغيل واضحة من الخدمة قبل متابعة التجربة.", null, "", "warning", 0);
		if (v.fault !== "none") {
			const sensorText = v.equipment?.irrigation?.status === "closed" && finite$2(v.irrigation_flow_lpm) && v.irrigation_flow_lpm === 0 ? "انقطعت قراءة الكلور فأُغلق الري افتراضيًا. قد تستمر المعالجة؛ أزل العطل لاستعادة القراءة." : "انقطعت قراءة الحساس. راقب حالة صمام الري؛ لم تتأكد حالة إغلاقه وتوقف تدفقه بعد.";
			return result("fault", v.fault === "sensor_dropout" ? "قراءة الحساس منقطعة" : "سيناريو عطل قيد التجربة", v.fault === "sensor_dropout" ? sensorText : reason(v) || "هناك عطل افتراضي مفعّل. أزله للعودة إلى التشغيل الاعتيادي.", "restore", "إزالة العطل ومتابعة التشغيل", "warning", 2);
		}
		if (v.mode !== "auto") return result("mode", "المحطة في وضع تشغيل آخر", `${reason(v) || (v.mode === "backwash" ? "الغسيل العكسي مفعّل." : "المحطة في وضع الاستعداد.")} عُد إلى التشغيل الاعتيادي لمتابعة التجربة.`, "restore", "متابعة التجربة", "idle", 0);
		if (!v.running || data.session?.status === "paused") return result("paused", "التجربة متوقفة مؤقتًا", "الزمن والعدادات ثابتة. تابع التجربة لتتحرك المياه من جديد.", "resume", "متابعة التجربة", "idle", 0);
		if (v.safety_state !== "REUSE" || v.equipment?.irrigation?.status !== "open" || !finite$2(v.irrigation_flow_lpm) || v.irrigation_flow_lpm <= 0) return result("waiting", v.safety_state === "HOLD" ? "الري محجوز حاليًا" : "ننتظر جاهزية الري", reason(v) || "لم تتأكد حالة الري وتدفقه من الخدمة بعد. انتظر تحديث الحالة.", null, "", "warning", 1);
		const progress = journeyProgress(ui, v.sessionId);
		if (progress.complete && ui?.experienceSession === v.sessionId && ui?.experienceRestored === true) return result("done", "عاد الري بعد استعادة القراءة", "أزلت العطل وعاد تدفق الري في المحاكاة. يمكنك مراجعة النتيجة أو تكرار اختبار الحساس.", "test", "جرّب انقطاع الحساس", "good", 3);
		if (!progress.complete) return result("journey", progress.stage.title, progress.stage.role, progress.index === progress.total - 1 ? "test" : "journey-next", progress.index === progress.total - 1 ? "جرّب انقطاع الحساس" : `التالي: ${WATER_JOURNEY[progress.index + 1].short}`, "good", 1);
		return result("normal", "المحطة تعمل والري متاح", "جرّب انقطاع قراءة الحساس وشاهد كيف يستجيب النظام.", "test", "جرّب انقطاع الحساس", "good", 1);
	}
	//#endregion
	//#region mawrid-system/client/presentation.js
	function readingDuration(stage) {
		const words = [
			stage?.title,
			stage?.role,
			stage?.benefit
		].filter(Boolean).join(" ").trim().split(/\s+/).filter(Boolean).length;
		return Math.max(2e4, Math.min(3e4, Math.ceil(words / 1.35 + 6) * 1e3));
	}
	var PRESENTATION_DURATION = WATER_JOURNEY.reduce((sum, stage) => sum + readingDuration(stage), 0);
	var JourneyPresentation = class {
		constructor() {
			this.stop();
		}
		stop() {
			this.status = "idle";
			this.sessionId = null;
			this.index = 0;
			this.remainingMs = 0;
			this.durationMs = 0;
			this.waitingCamera = false;
			this.lastAt = null;
			this.waitingSince = null;
			this.reason = "";
		}
		start(sessionId, now) {
			if (typeof sessionId !== "string" || !sessionId) throw new Error("A virtual session is required");
			this.sessionId = sessionId;
			this.index = 0;
			this.status = "playing";
			this.reason = "";
			this.prepare(now);
		}
		prepare(now) {
			this.durationMs = readingDuration(WATER_JOURNEY[this.index]);
			this.remainingMs = this.durationMs;
			this.waitingCamera = true;
			this.lastAt = null;
			this.waitingSince = now;
		}
		settle(id, now) {
			if (this.status !== "playing" || !this.waitingCamera || WATER_JOURNEY[this.index].id !== id) return false;
			this.waitingCamera = false;
			this.lastAt = now;
			this.waitingSince = null;
			return true;
		}
		consume(now) {
			if (this.status === "playing" && !this.waitingCamera && this.lastAt !== null) {
				this.remainingMs = Math.max(0, this.remainingMs - Math.max(0, now - this.lastAt));
				this.lastAt = Math.max(now, this.lastAt);
			}
		}
		tick(now) {
			this.consume(now);
			if (this.status !== "playing" || this.waitingCamera || this.remainingMs > 0) return false;
			if (this.index === WATER_JOURNEY.length - 1) {
				this.status = "complete";
				this.lastAt = null;
				this.reason = "";
				return true;
			}
			this.index++;
			this.prepare(now);
			return true;
		}
		pause(reason, now) {
			if (this.status !== "playing") return false;
			this.consume(now);
			this.status = "paused";
			this.reason = reason;
			this.lastAt = null;
			return true;
		}
		resume(now) {
			if (this.status !== "paused") return false;
			this.status = "playing";
			this.reason = "";
			this.waitingCamera = true;
			this.waitingSince = now;
			this.lastAt = null;
			return true;
		}
		view() {
			return {
				status: this.status,
				sessionId: this.sessionId,
				index: this.index,
				remainingMs: this.remainingMs,
				durationMs: this.durationMs,
				waitingCamera: this.waitingCamera,
				reason: this.reason
			};
		}
	};
	//#endregion
	//#region mawrid-system/client/guide.js
	var esc$1 = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		"\"": "&quot;",
		"'": "&#39;"
	})[c]);
	var finite$1 = (v) => typeof v === "number" && Number.isFinite(v);
	var n = (v, d = 1) => finite$1(v) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: d }).format(v) : "—";
	var icon$1 = (id) => `<svg aria-hidden="true"><use href="#i-${id}"/></svg>`;
	var value = (v, u = "") => `<bdi>${n(v)}</bdi>${u ? ` <small>${esc$1(u)}</small>` : ""}`;
	var list = (rows) => `<ul class="g-list">${rows.map((x) => `<li>${esc$1(x)}</li>`).join("")}</ul>`;
	var disclosure = (title, body, open = false) => `<details class="g-disclosure"${open ? " open" : ""}><summary>${esc$1(title)}</summary><div class="g-disclosure-body">${body}</div></details>`;
	var note = (text) => `<p class="g-note">${icon$1("info")}<span>${text}</span></p>`;
	var button = (action, label, primary = false, extra = "") => `<button type="button" class="button${primary ? " primary" : ""}" data-action="${action}" ${extra}>${label}</button>`;
	function illustration() {
		return `<svg viewBox="0 0 620 350" class="g-illustration" role="img" aria-label="مياه الوضوء والمغاسل تمر بالمعالجة والتحقق ثم تتجه إلى ري المسطحات"><defs><linearGradient id="g-water" x2="0" y2="1"><stop stop-color="#8fc2b9"/><stop offset="1" stop-color="#2e796b"/></linearGradient></defs><path d="M30 292H593" stroke="#dce6da" stroke-width="2"/><g fill="none" stroke="#4c8a79" stroke-width="8" stroke-linejoin="round"><path d="M528 130V233H471M373 233H332M272 233H237M177 233H120V191H83"/><path stroke="#bb9c6b" stroke-width="3" stroke-dasharray="6 6" d="M177 233V278H311V253"/></g><g stroke="#295c4d" stroke-width="2"><path fill="#edf3e8" d="M443 147h51v130h-51z"/><ellipse fill="#fafcf5" cx="469" cy="147" rx="25" ry="8"/><path fill="url(#g-water)" stroke="none" d="M447 207h43v66h-43z"/><rect fill="#fafcf5" x="271" y="156" width="62" height="111" rx="24"/><rect fill="#dee8d3" x="276" y="209" width="52" height="37" rx="3"/><rect fill="#fafcf5" x="176" y="156" width="62" height="111" rx="24"/><rect fill="#566d5e" x="181" y="207" width="52" height="40" rx="3"/><rect fill="#f1e7cf" x="364" y="213" width="32" height="37" rx="8"/><path fill="#235844" d="m129 226 13 7-13 7Zm25 0-12 7 12 7Z"/></g><g stroke="#376d52" fill="#60875b" stroke-width="2"><path d="M76 285v-75M76 243c-28 3-42-21-30-31 21-3 31 13 30 31ZM76 225c28 3 42-21 30-31-21-3-31 13-30 31Z"/><path d="M98 284v-26m0 9c-20 2-26-13-19-19 13-2 19 8 19 19Z"/></g><g fill="#285e4d" text-anchor="middle" font-family="Plex,Tahoma,sans-serif" font-size="18"><text x="511" y="93">وضوء ومغاسل</text><text x="302" y="126">معالجة</text><text x="171" y="126">تحقّق</text><text x="78" y="168">ريّ</text></g><g fill="#4d665a" font-family="Plex,Tahoma,sans-serif" text-anchor="middle" font-size="13"><text x="469" y="321">نجمع</text><text x="300" y="321">نرشّح</text><text x="203" y="321">نراقب</text><text x="78" y="321">نعيد الاستخدام</text></g><circle cx="206" cy="171" r="16" fill="#f7fbf1" stroke="#638567"/><path d="m198 170 6 6 10-12" fill="none" stroke="#376d52" stroke-width="3"/></svg>`;
	}
	function home(data) {
		const v = plantView(data);
		return `<section class="g-hero"><div class="g-hero-copy"><span class="g-kicker">مورد / محاكاة برمجية محلية</span><h2>مياه استُخدمت.<br>وفرصة تبدأ من جديد.</h2><p class="g-lead">منظومة تعيد استخدام مياه الوضوء والمغاسل لري المسطحات، وتضيف طبقة مراقبة وقرار وسجل إلى رحلة الماء.</p><p>هنا يمكنك تشغيل محطة افتراضية، متابعة الماء، وتجربة ما يحدث عند تعطل حساس أو تغيّر الجودة.</p><div class="g-actions"><a class="button primary" href="#plant">جرّب المحطة الآن ${icon$1("arrow")}</a><a class="g-text-link" href="#components">كيف يعمل مورد؟</a></div><span class="g-caption">لا تحتاج خبرة تقنية · رحلة ماء موجهة خطوة بخطوة</span></div><div class="g-hero-art">${illustration()}<span class="g-art-caption">من المصدر إلى الاستخدام، مع تحقق في الطريق</span></div></section>
  <div class="g-honesty"><span class="g-status-dot"></span><div><strong>أنت داخل محاكاة برمجية تفاعلية.</strong><p>حركة المياه والأعطال والقراءات تحسب محليًا. لا محطة ميدانية متصلة، ولا شهادة جودة ماء.</p></div><a href="#technology">كيف بُنيت؟ ${icon$1("arrow")}</a></div>
  ${disclosure("ماذا يقدّم مورد؟ وحدة متكاملة وصندوق للمحطات القائمة", `<section class="g-section g-products"><div><span class="g-kicker">قلب واحد، طريقتان للتطبيق</span><h2>ما الذي يقدمه مورد؟</h2><p>المعالجة وحدها لا تكفي؛ مورد يربط القياس بقرار مفهوم يمكن مراجعته.</p></div><article><span class="g-product-number">01 / UNIT</span><h3>وحدة مورد</h3><p>محطة معالجة مدمجة مع المراقبة والتحكم، للمواقع التي تحتاج خط معالجة كاملًا.</p><a href="#plant">استكشف الوحدة الافتراضية ←</a></article><article><span class="g-product-number">02 / BOX</span><h3>صندوق مورد</h3><p>تصوّر طبقة تحقق ومتابعة تضاف إلى محطة قائمة. يحتاج تصميم تكامل وتأهيلًا لكل موقع.</p><a href="#technology">افهم طبقة التحقق ←</a></article></section>`)}
  <section class="g-section"><div class="g-section-heading"><h2>تريد معرفة المزيد؟</h2></div><div class="g-audience-links"><a href="#plant"><strong>أريد تجربة واضحة</strong><span>لأي زائر، دون مصطلحات</span>${icon$1("arrow")}</a><a href="#follow"><strong>أتابع تشغيل المحطة</strong><span>الحالة والسبب والقراءات</span>${icon$1("arrow")}</a><a href="#technology"><strong>أريد التفاصيل التقنية</strong><span>البرمجة والذكاء وحدود الدليل</span>${icon$1("arrow")}</a></div></section>${v.active ? `<p class="g-note">لديك جلسة محاكاة محفوظة. فتح الصفحات لا يعيد تشغيلها أو يمسح سجلها.</p>` : ""}`;
	}
	var TOUR = [
		{
			title: "شاهد التشغيل المعتاد",
			text: "ابدأ المحاكاة، ثم لاحظ تدفق المعالجة وحالة الري. الأرقام تأتي من محرك واحد، ويقرأها المجسم كما هي.",
			action: "guide-normal",
			label: "تشغيل اعتيادي",
			focus: "raw"
		},
		{
			title: "جرّب فقدان قراءة الحساس",
			text: "سنحاكي غياب قراءة الكلور. راقب رسالة السبب وتوقف الري؛ القيمة المفقودة تظهر «غير متاحة» ولا تُستبدل بصفر.",
			action: "guide-fault",
			label: "جرّب انقطاع الحساس",
			focus: "valve"
		},
		{
			title: "أزل العطل وراجع النتيجة",
			text: "أعد القراءة الافتراضية، ثم تحقق من حالة المحطة. يبقى سبب الإيقاف اليدوي، إن فُعّل، حتى يلغيه المشغّل صراحةً.",
			action: "guide-clear",
			label: "إزالة العطل",
			focus: "treated"
		}
	];
	function tourPanel(ui) {
		const step = Math.min(2, Math.max(0, ui.tourStep || 0)), t = TOUR[step];
		return `<div class="g-tour"><div class="g-tour-top"><strong>جولة إرشادية</strong><span>الخطوة ${step + 1} من 3</span></div><ol class="g-tour-steps">${TOUR.map((x, i) => `<li${step === i ? " aria-current=\"step\"" : ""}><button data-action="guide-tour" data-step="${i}" aria-label="الخطوة ${i + 1}: ${esc$1(x.title)}" aria-pressed="${step === i}">${i + 1}</button><span>${esc$1(x.title)}</span></li>`).join("")}</ol><h3 tabindex="-1">${esc$1(t.title)}</h3><p>${esc$1(t.text)}</p><div class="g-actions">${button(t.action, t.label, true, "data-plant-control")}${step < 2 ? button("guide-tour-next", "الخطوة التالية ←") : "<a class=\"g-text-link\" href=\"#follow\">راجع سجل التجربة ←</a>"}</div><p class="g-caption">اختيار الخطوة لا يغيّر المحطة؛ زر التجربة هو الذي ينفّذ الأمر.</p></div>`;
	}
	function status(data, connected) {
		const v = plantView(data), p = data?.virtual_plant;
		const waiting = !connected && !data;
		const title = waiting ? "جارٍ الاتصال بالخدمة المحلية" : !connected ? "انقطع الاتصال" : !v.active ? "المحاكاة لم تبدأ" : !v.running ? "المحاكاة متوقفة مؤقتًا" : v.process_state || "حالة غير متاحة";
		return `<div class="g-current ${waiting ? "idle" : !connected ? "offline" : v.safety_state === "HOLD" ? "hold" : v.active ? "ready" : "idle"}" role="status"><span class="g-status-dot"></span><div><strong>${esc$1(title)}</strong><p>${waiting ? "ننتظر حالة المحطة من الخدمة؛ الأوامر تتاح بعد الاتصال." : !connected ? "المعروض آخر لقطة مستلمة. الأوامر معطلة حتى يعود الاتصال." : !v.active ? "اضغط «بدء المحاكاة»؛ لا تحتاج اختيار ملفات أو مصادر." : !v.running ? "الزمن والعدادات ثابتة، والحالات المعروضة من آخر لقطة. اضغط «متابعة المحاكاة» لاستئناف الزمن." : p?.safety?.reasons?.length ? p.safety.reasons.map(esc$1).join(" · ") : "شروط قواعد المحاكاة متحققة؛ هذا وصف تشغيلي افتراضي."}</p></div></div>`;
	}
	function liveStats(data) {
		const v = plantView(data);
		return `<div class="g-live-metrics"><article><span>${v.active && !v.running ? "الري في اللقطة المثبتة" : "الري الآن"}</span><strong>${v.active ? v.equipment?.irrigation?.status === "open" ? "مفتوح افتراضيًا" : v.equipment?.irrigation?.status === "closed" ? "مغلق افتراضيًا" : "غير متاح" : "لم يبدأ"}</strong><small>${v.active && !v.running ? "الزمن موقوف؛ لا تراكم للترات" : "حالة الصمام من المحرك"}</small></article><article><span>${v.active && !v.running ? "تدفق اللقطة المثبتة" : "تدفق المعالجة"}</span><strong>${value(v.treatment_flow_lpm, "لتر/دقيقة")}</strong><small>${v.active && !v.running ? "قيمة اللقطة؛ الزمن متوقف" : "الكمية المارة في الخط الآن"}</small></article><article><span>الماء المستخدم للري</span><strong>${value(v.irrigation_liters, "لتر")}</strong><small>إجمالي محاكى لهذه الجلسة</small></article></div>`;
	}
	function readings(data) {
		const v = plantView(data), p = data?.virtual_plant;
		return `<div class="g-reading-grid">${[
			[
				"العكارة",
				v.readings?.outlet_turbidity,
				"NTU",
				"وضوح الماء"
			],
			[
				"الكلور المتبقي",
				v.readings?.chlorine,
				"mg/L",
				"إشارة التعقيم"
			],
			[
				"الأس الهيدروجيني",
				v.readings?.ph,
				"pH",
				"الحموضة والقلوية"
			],
			[
				"فرق ضغط الوسائط",
				v.filter_delta_pressure_bar,
				"bar",
				"مقاومة المرشح"
			]
		].map(([title, x, u, hint]) => `<article><span>${title}</span><strong>${finite$1(x) ? value(x, u) : "غير متاحة"}</strong><small>${hint} · قراءة افتراضية</small></article>`).join("")}</div>${p ? `<p class="g-caption">ساعة المحاكاة: <bdi>${esc$1(p.timestamp?.replace("T", " ").replace(/\.\d+Z$/, " UTC"))}</bdi> · سرعة الزمن <bdi>×${esc$1(v.speed)}</bdi></p>` : ""}`;
	}
	function controls(data) {
		const v = plantView(data);
		return `<div class="g-primary-controls">${!v.active ? button("plant-start", icon$1("play") + "بدء المحاكاة", true, "data-mutation") : button("plant-running", icon$1(v.running ? "pause" : "play") + (v.running ? "إيقاف مؤقت" : "متابعة المحاكاة"), true, "data-plant-control")}<label>سرعة الزمن<select id="guide-speed" data-plant-control aria-label="سرعة زمن المحاكاة">${[
			[1, "طبيعية ×1"],
			[10, "أسرع ×10"],
			[30, "أسرع ×30"]
		].map(([x, t]) => `<option value="${x}"${v.speed === x ? " selected" : ""}>${t}</option>`).join("")}</select></label></div>`;
	}
	function experiments(data) {
		const v = plantView(data);
		return `<label class="g-field">ماذا تريد اختباره؟<select id="plant-fault" data-plant-control>${Object.entries(PLANT_FAULTS).map(([id, t]) => `<option value="${id}"${v.fault === id ? " selected" : ""}>${esc$1(t)}</option>`).join("")}</select></label><p class="g-caption">اختيار السيناريو يغيّر المحاكاة فورًا. لا أعطال أو أوامر على أجهزة حقيقية.</p><label class="g-field">وضع المحطة<select id="plant-mode" data-plant-control>${[
			["auto", "معالجة تلقائية"],
			["standby", "استعداد بلا تدفق"],
			["backwash", "غسيل عكسي للمرشح"]
		].map(([id, t]) => `<option value="${id}"${v.mode === id ? " selected" : ""}>${t}</option>`).join("")}</select></label>`;
	}
	function presentationPanel(data, ui, connected) {
		const x = experienceState(data, ui, connected), p = ui.presentation || { status: "idle" }, status = p.status;
		const eligible = [
			"start",
			"paused",
			"journey",
			"normal",
			"done"
		].includes(x.id) && connected;
		const title = status === "playing" ? "العرض التلقائي يعمل" : status === "paused" ? {
			reading: "متوقف للقراءة",
			camera: "متوقف لاستكشاف المجسم",
			details: "متوقف لقراءة التفاصيل",
			hidden: "متوقف بعد مغادرة التبويب",
			navigation: "متوقف بعد مغادرة التجربة",
			plant: "متوقف بسبب حالة المحاكاة",
			connection: "متوقف بسبب انقطاع الاتصال",
			manual: "متوقف للتحكم اليدوي"
		}[p.reason] || "العرض متوقف" : status === "complete" ? "اكتملت رحلة الماء" : "شاهد رحلة الماء تلقائيًا";
		const text = status === "playing" ? "الكاميرا تقرّب الجزء، ثم تمنحك وقتًا لقراءة الشرح." : status === "paused" ? x.id === "journey" ? "المهلة محفوظة. تابع العرض من الزر أسفل الشرح." : "المهلة محفوظة. راجع حالة المحاكاة أدناه أولًا." : status === "complete" ? "شاهدت المراحل الثماني. اختبار الحساس خيار مستقل أسفل الشرح." : `٨ مراحل · نحو ${Math.round(PRESENTATION_DURATION / 6e4)} دقائق · يبدأ من التجميع ويقرّب كل جزء`;
		const start = status === "idle" || status === "complete" ? button("auto-start", status === "complete" ? "إعادة العرض" : ["start", "paused"].includes(x.id) ? "تشغيل وعرض تلقائي" : "ابدأ العرض التلقائي", false, `data-auto-start${eligible ? "" : " disabled"}`) : "";
		return `<div class="x-presentation-copy"><strong>${esc$1(title)}</strong><p>${esc$1(text)}</p></div><div class="x-presentation-action">${start}<span id="presentation-clock" role="timer" aria-live="off"></span>${status === "playing" && p.textOnly ? "<small>عرض نصي؛ المجسم غير جاهز</small>" : ""}${status === "paused" && x.id !== "journey" ? button("auto-stop", "إنهاء العرض", false, "data-presentation-control") : ""}</div>`;
	}
	function experienceCoach(data, ui, connected) {
		const x = experienceState(data, ui, connected), v = plantView(data), p = journeyProgress(ui, v.sessionId), journey = x.id === "journey";
		const auto = ui.presentation?.sessionId === v.sessionId ? ui.presentation?.status : "idle", presenting = journey && ["playing", "paused"].includes(auto);
		const previous = journey && p.index > 0 && !presenting ? button("journey-previous", "← السابق", false, "data-journey-nav") : "";
		const replay = (x.id === "done" || x.id === "normal") && !presenting ? button("journey-replay", "شرح المسار من البداية", false, "data-journey-nav") : "";
		const manual = presenting ? button("auto-stop", "العودة للعرض اليدوي", false, "data-presentation-control") : "";
		const primary = presenting ? button(auto === "playing" ? "auto-pause" : "auto-resume", auto === "playing" ? "إيقاف العرض" : "متابعة العرض", true, "data-presentation-control") : x.action ? button("experience-next", esc$1(x.label), true, `data-mutation data-command="${esc$1(x.action)}"`) : "<span class=\"x-wait\">ننتظر حالة المحطة</span>";
		return `<div class="x-coach-copy"><div class="x-coach-progress"><span class="x-step">${journey ? `رحلة الماء · ${p.index + 1} من ${p.total}` : [
			"ابدأ من هنا",
			"شاهد التشغيل",
			"جرّب الحماية",
			"نتيجة التجربة"
		][x.step] || "حالة المحطة"}</span>${journey ? `<span class="x-progress-dots" aria-hidden="true">${Array.from({ length: p.total }, (_, i) => `<i class="${i === p.index ? "current" : i < p.index ? "passed" : ""}"></i>`).join("")}</span>` : ""}</div><h2>${esc$1(x.title)}</h2>${journey ? `<p class="x-stage-role">${esc$1(p.stage.role)}</p><p class="x-stage-benefit"><strong>الفائدة:</strong> ${esc$1(p.stage.benefit)}</p>` : `<p>${esc$1(x.text)}</p>`}</div><div class="x-coach-action">${primary}${previous || replay || manual ? `<div class="x-coach-secondary">${previous}${replay}${manual}</div>` : ""}</div>`;
	}
	function experienceStatus(data, connected) {
		const v = plantView(data), known = v.active && connected;
		const title = !connected ? data ? "انقطع الاتصال · آخر لقطة" : "جارٍ الاتصال" : !v.active ? "جاهزة للتجربة" : !v.running ? "متوقفة مؤقتًا" : v.safety_state === "REUSE" && v.equipment?.irrigation?.status === "open" && v.irrigation_flow_lpm > 0 ? "الري يعمل" : v.process_state || "بانتظار الحالة";
		return `<span class="x-live ${!known ? "idle" : !v.running ? "paused" : v.safety_state === "REUSE" ? "running" : "hold"}"><i></i>${esc$1(title)}</span>`;
	}
	function plant(data, ui) {
		return `<section class="x-experience" aria-label="تجربة محطة مورد">
  <header class="x-header"><a href="#start" class="x-brand" aria-label="مورد، العودة إلى البداية"><img src="/assets/mark.svg" alt="" width="27" height="32"><strong>مورد</strong></a><span class="x-simulation">محاكاة برمجية</span><a class="x-exit" href="#start">العودة إلى مورد ${icon$1("arrow")}</a></header>
  <div class="x-intro"><div><h1>من مياه الوضوء والمغاسل إلى الريّ.</h1><p>اتبع الجزء المضاء خطوة بخطوة، ثم جرّب حماية مسار الري.</p></div><button class="x-detail-button" data-action="experience-details">التفاصيل ${icon$1("info")}</button></div>
  <section class="x-presentation" data-guide-region="presentation" aria-label="العرض التلقائي"></section>
  <div class="x-scene"><div class="x-scene-status" data-guide-region="experience-status"></div><iframe id="guide-scene" src="/plant3d/index.html?embed=1&simple=1" title="محطة مورد الافتراضية؛ اسحب للدوران واختر جزءًا لمعرفة فائدته" loading="eager"></iframe><span class="x-scene-hint">الإضاءة تشرح ترتيب الأجزاء · حركة الماء من المحاكاة</span></div>
  <div class="x-coach" data-guide-region="experience-coach" aria-live="polite" aria-atomic="true"></div><p class="x-busy" id="experience-busy" role="status" hidden>جارٍ تنفيذ الخطوة…</p><p class="x-command-error" id="experience-error" role="alert" hidden></p>
  <footer class="x-footer"><span>خطوات الشرح ليست زمن عبور الماء · الذكاء في <a href="#model">المختبر البحثي</a></span><span class="x-utility"><span data-guide-region="experience-pause"></span><a href="#follow">الحالة والسجل ←</a></span></footer>
  <dialog id="experience-details" class="x-dialog" aria-labelledby="experience-details-title"><header><h2 id="experience-details-title">تفاصيل المحطة</h2><button class="icon-button" data-action="experience-close" aria-label="إغلاق التفاصيل">${icon$1("close")}</button></header><p>المجسم يقرأ حالة المحرك المحلي. لا أجهزة ميدانية متصلة، ولا شهادة جودة ماء.</p><nav class="x-detail-links" aria-label="استكشف التفاصيل"><a href="#components">كل جزء وفائدته ←</a><a href="#technology">البرمجة والذكاء وحدود المحاكاة ←</a><a href="#follow">الحالة والسجل ←</a></nav><div data-guide-region="stats"></div><div data-guide-region="readings"></div>${disclosure("خيارات تشغيل إضافية", `<p>هذه الخيارات تغيّر المحاكاة الحالية. يمكنك العودة للتجربة الموجّهة في أي وقت.</p><div data-guide-region="controls"></div>${experiments(data)}<p class="g-caption">بدء تجربة جديدة ينشئ جلسة منفصلة ويحفظ سجل السابقة.</p>${button("plant-start", "بدء تجربة جديدة", false, "data-mutation")}`)}</dialog>
</section>`;
	}
	var primaryIds = [
		"source",
		"inlet",
		"strainer",
		"raw",
		"feed",
		"flow_meter",
		"dose_pre",
		"media",
		"dose_dechlor",
		"orp",
		"carbon",
		"pilot",
		"cartridge",
		"dose_ph",
		"dose_final",
		"quality",
		"compliance",
		"uv",
		"treated",
		"reuse",
		"valve"
	];
	function components(ui) {
		const current = guideContent.components.find((x) => x.id === ui.component) || guideContent.components[0];
		const rows = [...guideContent.components].sort((a, b) => {
			const i = primaryIds.indexOf(a.id), j = primaryIds.indexOf(b.id);
			return (i < 0 ? 99 : i) - (j < 0 ? 99 : j);
		});
		return `<div class="g-section-heading"><div><span class="g-kicker">رحلة الماء وما حولها</span><h2>كل جزء له مهمة واضحة</h2><p>اختر اسم الجزء. ستجد ما يفعله، فائدته، وكيف تمثله هذه النسخة.</p></div></div><div class="g-component-layout"><nav class="g-component-list" aria-label="أجزاء مورد"><label class="g-part-search">ابحث عن جزء<input id="guide-component-search" type="search" placeholder="مثل: الكربون أو الحساس" autocomplete="off"></label><p id="guide-component-count" class="g-caption">أجزاء الدليل: ${rows.length}</p>${rows.map((x, i) => `<button data-action="guide-component" data-component="${esc$1(x.id)}" aria-pressed="${current.id === x.id}"><span>${String(i + 1).padStart(2, "0")}</span>${esc$1(x.title)}${icon$1("arrow")}</button>`).join("")}</nav><section class="g-component-detail" id="guide-component-detail" tabindex="-1">${componentDetail(current)}</section></div>${disclosure("ماذا تغيّر عن النموذج السابق؟", `<p>مرجع التجهيزات هو ملف «محطة مورد للمياه الرمادية»: خزانا 5 م³، ترتيب أربع جرعات، ترشيح وسائط وكربون وخراطيش، وصمام مطابقة بإعادة للخام ثم UV وخزان المنتج. يوضح المجسم هذا الترتيب؛ الحساب الحجمي يجمع الخط في نموذج واحد.</p><p>الجرعات وفعالية التعقيم والامتزاز ومؤشرات المختبر لا تحسب في هذه النسخة. التفاصيل التجريبية والسحابة معرّفة كلٌّ بحالتها، ولا توجد نتائج حساسات مصطنعة لها.</p>`)}${note("الدليل يشرح تصميم مورد؛ لا يشكل مخطط تصنيع أو إثبات امتثال. <a href=\"#technology\">راجع حدود المحاكاة والاختبار.</a>")}`;
	}
	function componentDetail(x) {
		return `<span class="g-kicker">دليل المكونات</span><h2>${esc$1(x.title)}</h2><p class="g-lead">${esc$1(x.role)}</p><dl class="g-definition"><div><dt>ما فائدته؟</dt><dd>${esc$1(x.benefit)}</dd></div><div><dt>كيف يعمل؟</dt><dd>${esc$1(x.how)}</dd></div><div><dt>ما الذي تراه هنا؟</dt><dd>${esc$1(x.simulated)}</dd></div><div><dt>حدود النسخة الحالية</dt><dd>${esc$1(x.limitation)}</dd></div></dl><div class="g-actions"><a href="#plant" class="button primary">شاهد المحطة ${icon$1("arrow")}</a></div>`;
	}
	function technology() {
		return `<section class="g-tech-intro"><span class="g-kicker">شرح مفتوح، بقدر يخدم الفهم</span><h2>كيف يفكّر النظام؟<br>وما الذي أثبتناه فعلًا؟</h2><p class="g-lead">المجسم يعرض الحالة، ومحرك المحاكاة يحسبها، وقواعد التشغيل تفسّر القرار. النموذج البحثي يُختبر في مسار مستقل.</p></section><div class="g-layer-diagram" aria-label="طبقات النظام"><article><span>01</span><h3>مصدر القراءة</h3><p>محاكاة محلية، أو إعادة عرض بيانات بحثية، أو استقبال API. لكل جلسة مصدر واحد معلن.</p></article><article><span>02</span><h3>التحليل والقرار</h3><p>قواعد للمحطة الافتراضية. استدلال بحثي للنموذج على مصادره المؤهلة فقط.</p></article><article><span>03</span><h3>العرض والتوثيق</h3><p>واجهة ومجسم يقرآن الحالة نفسها، وسجل محلي لكل قراءة وتنبيه وقرار.</p></article></div>
  ${disclosure("اشرح لي الكود البرمجي وبنية النظام", `<p>تطبيق محلي: Python للخدمة والحساب، SQLite للسجل، JavaScript للواجهة، وThree.js للمجسم. هذه مسؤوليات الأجزاء وكيف تنتقل الحالة بينها:</p><ol class="g-explain-steps">${[
			["مصدر واحد لكل جلسة", "الجلسة تحمل هوية ومصدرًا معلنًا. بيانات المحاكاة لا تتحول إلى بيانات حساسات، وملفات البحث لا تُخلط بقراءات API. تُرفض الأوامر والقيم غير الصالحة وتبقى القراءة المفقودة مفقودة."],
			["ساعة مستقلة عن الشاشة", "عامل خلفي يقدم زمن المحاكاة وفق السرعة المختارة. قراءة الشاشة للحالة لا تقدم الزمن. التوقف المؤقت يثبت الساعة والحجوم؛ تحديث الصفحة لا ينشئ جلسة جديدة."],
			["حساب حركة الماء", "في كل خطوة يحسب المحرك الداخل والمسحوب والمنتج والري والغسيل والفائض. يحد السحب بالمخزون المتاح، ويختبر توازن الكتلة وعدم تجاوز السعات. هذه حسابات حجمية؛ لا تحسب إزالة الملوثات أو التعقيم."],
			["قرار واضح وله سبب", "تطبّق قواعد ثابتة على القراءات والحالة. فقد حساس أو خلل أو احتجاز يدوي ينتج حالة احتجاز وسببًا محفوظًا. أمر فتح الصمام منفصل عن تأكيد موضعه، ويمكن تجربة اختلافهما. لا تُرسل أوامر لعتاد فعلي."],
			["الحفظ قبل إعلان الحالة", "يحضر المحرك الحالة التالية، ثم يحفظ القراءة واللقطة والحدث في معاملة قاعدة بيانات. عند فشل الحفظ لا تُنشر خطوة غير محفوظة. سجل الجلسات السابقة يبقى عند بدء جلسة جديدة."],
			["لقطة واحدة للمتابعة والمجسم", "تعرض الخدمة الحالة عبر API محلي. يقرأ المتصفح والمجسم اللقطة بدل توليد أرقام مستقلة. وبعد أمر تشغيل يطلب المجسم قراءة جديدة. حركة الأسهم بصرية فقط، ولا تُستخدم لحساب لترات."],
			["مسار منفصل للذكاء", "في مختبر البحث وحده، تُمرر قنوات المصدر المؤهل إلى حزمة النموذج المثبتة. وسوم الحقيقة للتقييم لا تُمرر كمدخل للاستدلال. النتيجة والسياق والإتاحة تُحفظ، ولا يُفتح بها صمام. استقبال API والمحاكاة لا يفعّلان هذا النموذج."],
			["إيصال يمنع تكرار الرسالة", "في استقبال القياسات يحمل كل قياس معرفًا ثابتًا. إعادة إرساله بعد ضياع الرد تعيد إيصال الحفظ نفسه دون إنشاء قراءة ثانية. الحفظ الناجح لا يثبت صحة القياس أو جودة الماء."]
		].map(([title, text], i) => `<li><span>${i + 1}</span><div><h3>${esc$1(title)}</h3><p>${esc$1(text)}</p></div></li>`).join("")}</ol><p>نشرح البنية والمبدأ والسلوك المرئي. معاملات الضبط والوصفات وأوزان النماذج وتفاصيل التشغيل الخاصة لا تنشر في هذا الشرح.</p>`, true)}
  ${disclosure("كيف أستخدم النظام خطوة بخطوة؟", `<ol class="g-explain-steps">${guideContent.softwareSteps.map((x, i) => `<li><span>${i + 1}</span><div><h3>${esc$1(x.title)}</h3><p>${esc$1(x.text)}</p></div></li>`).join("")}</ol><p>هذا شرح بنية وسلوك قابل للمراجعة. تفاصيل الضبط الداخلية، وصفات المعالجة، وأوزان النموذج لا تعرض هنا. الواجهة لا ترسل الكود أو البيانات لخدمة خارجية.</p>`)}
  ${disclosure("كيف يعمل الذكاء الاصطناعي المستخدم؟", `<p class="g-lead">${esc$1(guideContent.ai.plain)}</p><dl class="g-definition"><div><dt>الطريقة</dt><dd>${esc$1(guideContent.ai.algorithm)}</dd></div><div><dt>بيانات التعلم</dt><dd>${esc$1(guideContent.ai.data)}</dd></div><div><dt>حدود سلطة الذكاء</dt><dd>${esc$1(guideContent.ai.safety)}</dd></div></dl><h3>كيف نختبره؟</h3>${list(guideContent.ai.validation)}<h3>ما الذي لا يثبته؟</h3>${list(guideContent.ai.limits)}<h3>الإصدارات هنا</h3>${list(guideContent.ai.versions)}<a class="button" href="#model">افتح مختبر الذكاء البحثي ${icon$1("arrow")}</a>`)}
  ${disclosure("هل هذه محاكاة حقيقية أم حركة مرسومة؟", `<p>هناك حساب برمجي حقيقي للمخزون والتدفق والزمن. يحدّ كل انتقال مقدار الماء المتاح، وتُراجع معادلة توازن الكتلة: المخزون الأولي + الداخل = المخزون الحالي + الري + التصريف + الغسيل + الفائض. لا تجمع الواجهة لترات من حركة الأسهم.</p><p>المجسم يقرأ لقطة المحرك كل ثانيتين. عند الإيقاف تتوقف ساعة المحاكاة، وعند فقد الاتصال تتوقف الحركة وتظل آخر لقطة موضحة. طلب الصمام منفصل عن تأكيد موضعه.</p><p>لكنها ليست نموذجًا كيميائيًا أو هيدروليكيًا معايرًا، ولا نسخة موثقة من محطة ميدانية. قيم الجودة إشارات توضيحية، والمعالجة والجرعات وUV ليست نتائج مختبر محسوبة. لا يصح وصفها بضمان أمان كل لتر.</p>`)}
  ${disclosure("ما المنجز وما المرحلة التالية؟", `<div class="g-maturity"><div><strong>يعمل في هذه النسخة</strong>${list(["محاكاة مخزون وتدفق، أعطال وقواعد تشغيل، مجسم مرتبط بالحالة، سجل وتصدير محلي.", "استدلال نموذج بحثي على إعادة عرض محدودة ومؤهلة من البيانات العامة."])}</div><div><strong>يحتاج تحققًا ميدانيًا</strong>${list([
			"أداء الحساسات والجرعات والمرشحات والتعقيم على مياه الموقع.",
			"تصنيف الأعطال الخمسة، ثقة كل حساس، وزمن الاستجابة على الأجهزة المستهدفة.",
			"التشغيل الفعلي والامتثال المختبري وقياس الوفر والجدوى."
		])}</div></div><p>الكربون التجاري هو نقطة البداية في التصميم. البيوتشار من مخلفات النخيل مسار بحثي تقارن نتائجه أولًا؛ لا يُعرض كبديل أثبت أداءه في مورد. التنبؤ بالطلب والمساعد العربي والسحابة متعددة المواقع مراحل لاحقة.</p>`)}
  ${disclosure("لماذا صُمّمت الصفحات بهذا التسلسل؟", `<p>بداية تشرح المهمة، إجراء أساسي واضح، تفاصيل عند الطلب، وأسماء ثابتة للصفحات. استرشدنا بالمراجع التالية وطبقناها على تجربة مورد؛ لم ننسخ قالبًا تجاريًا أو ندّعِ اختبار سهولة مع جميع فئات المحكمين.</p><ul class="g-source-links"><li><a href="https://design-system.service.gov.uk/patterns/start-using-a-service/" target="_blank" rel="noopener">GOV.UK — بداية واضحة للخدمة ↗</a></li><li><a href="https://designsystem.digital.gov/components/step-indicator/" target="_blank" rel="noopener">USWDS — إظهار التقدم في الخطوات ↗</a></li><li><a href="https://www.carbondesignsystem.com/building-blocks/core/components/accordion/guidelines" target="_blank" rel="noopener">IBM Carbon — تفاصيل قابلة للفتح ↗</a></li><li><a href="https://www.w3.org/WAI/tips/designing/" target="_blank" rel="noopener">W3C WAI — وضوح النص والتنقل والوصول ↗</a></li></ul>`)}
  <div class="g-next"><a href="#plant">جرّب القرار بنفسك ←</a><a href="#components">راجع أجزاء المحطة ←</a></div>`;
	}
	function follow(data) {
		const v = plantView(data);
		return `<div data-guide-region="status"></div><div data-guide-region="stats"></div><div class="g-follow-grid"><section><h2>القراءات التي تفسّر الحالة</h2><div data-guide-region="readings"></div><a class="button" href="#measurements">تفاصيل جميع القياسات ${icon$1("arrow")}</a></section><section><h2>ما الذي حدث؟</h2><div data-guide-region="events"></div><a class="button" href="#alerts">كل التنبيهات ${icon$1("arrow")}</a></section></div><section class="g-export"><div><span class="g-kicker">سجل يمكن مراجعته</span><h2>احتفظ بالسجل</h2><p>التصدير يشمل كل الجلسات المحفوظة مع مصادرها: المحاكاة والبحث وAPI. كميات المحاكاة ليست وفرًا ميدانيًا مقاسًا.</p></div><div class="g-actions">${button("export-report", "ملخص كل الجلسات")}${button("export-readings", "كل القراءات CSV")}<a class="g-text-link" href="#history">السجل التفصيلي ←</a></div></section>${!v.active ? note("المتابعة هنا تخص المحطة الافتراضية. <a href=\"#plant\">ابدأ المحاكاة</a> لعرض حالتها؛ تبقى الجلسات البحثية متاحة من المختبر.") : ""}`;
	}
	function events(data) {
		const rows = plantView(data).events?.slice(0, 5) || [];
		return rows.length ? `<ol class="g-events">${rows.map((a) => `<li><strong>${esc$1(a.title)}</strong><p>${esc$1(a.detail)}</p><small><bdi>${esc$1((a.received_at || a.timestamp)?.replace("T", " ").replace(/\.\d+Z$/, " UTC"))}</bdi> · وقت التسجيل</small></li>`).join("")}</ol>` : "<p class=\"g-empty\">لم تُسجَّل أحداث لهذه الجلسة حتى الآن. جرّب سيناريو انقطاع الحساس لقراءة سبب القرار.</p>";
	}
	var GUIDE_PAGES = [
		"start",
		"plant",
		"components",
		"technology",
		"follow"
	];
	function renderGuide(container, page, data, ui, connected, disabled = false, force = false) {
		if (force || container.dataset.guidePage !== page) {
			container.innerHTML = {
				start: () => home(data),
				plant: () => plant(data, ui),
				components: () => components(ui),
				technology,
				follow: () => follow(data)
			}[page]();
			container.dataset.guidePage = page;
		}
		const regions = {
			status: () => status(data, connected),
			stats: () => liveStats(data),
			readings: () => readings(data),
			events: () => events(data),
			"experience-coach": () => experienceCoach(data, ui, connected),
			"experience-status": () => experienceStatus(data, connected),
			presentation: () => presentationPanel(data, ui, connected),
			"experience-pause": () => plantView(data).active && plantView(data).running ? button("plant-running", "إيقاف المحاكاة", false, "data-plant-control") : ""
		};
		for (const [key, fn] of Object.entries(regions)) {
			const node = container.querySelector(`[data-guide-region="${key}"]`);
			if (node) {
				const html = fn();
				if (node.savedHTML !== html) {
					node.innerHTML = html;
					node.savedHTML = html;
				}
			}
		}
		const control = container.querySelector("[data-guide-region=\"controls\"]");
		if (control) {
			const active = plantView(data).active;
			if (control.dataset.active !== String(active)) {
				control.innerHTML = controls(data);
				control.dataset.active = String(active);
			}
			const run = control.querySelector("[data-action=\"plant-running\"]");
			if (run) {
				const running = plantView(data).running;
				run.innerHTML = icon$1(running ? "pause" : "play") + (running ? "إيقاف مؤقت" : "متابعة المحاكاة");
			}
		}
		const v = plantView(data);
		for (const [id, key] of [
			["guide-speed", "speed"],
			["plant-mode", "mode"],
			["plant-fault", "fault"]
		]) {
			const el = container.querySelector("#" + id);
			if (el && el !== document.activeElement) el.value = String(v[key] ?? (key === "speed" ? 1 : key === "mode" ? "auto" : "none"));
		}
		const experience = container.querySelector(".x-experience");
		if (experience) {
			experience.dataset.journey = String(experienceState(data, ui, connected).id === "journey");
			experience.dataset.presentation = ui.presentation?.status || "idle";
		}
		const error = container.querySelector("#experience-error");
		if (error) {
			error.hidden = !ui.experienceError;
			error.textContent = ui.experienceError || "";
		}
		container.querySelectorAll("[data-auto-start]").forEach((x) => {
			x.disabled = disabled || !connected || ![
				"start",
				"paused",
				"journey",
				"normal",
				"done"
			].includes(experienceState(data, ui, connected).id);
		});
		container.querySelectorAll("[data-journey-nav]").forEach((x) => {
			x.disabled = disabled || !connected;
		});
		container.querySelectorAll("[data-plant-control]").forEach((x) => {
			x.disabled = disabled || !connected || !v.active;
		});
	}
	function updateTour(container, ui) {
		const el = container.querySelector("#guide-tour-panel");
		if (el) {
			el.innerHTML = tourPanel(ui);
			el.querySelector("h3")?.focus({ preventScroll: true });
		}
	}
	function updateComponent(container, ui) {
		const x = guideContent.components.find((x) => x.id === ui.component);
		if (!x) return;
		const el = container.querySelector("#guide-component-detail");
		if (el) {
			el.innerHTML = componentDetail(x);
			el.focus({ preventScroll: true });
			if (matchMedia("(max-width: 760px)").matches) el.scrollIntoView({
				block: "start",
				behavior: "auto"
			});
		}
		container.querySelectorAll("[data-component]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.component === x.id)));
	}
	//#endregion
	//#region mawrid-system/client/app.js
	var $ = (selector) => document.querySelector(selector);
	var esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		"\"": "&quot;",
		"'": "&#39;"
	})[c]);
	var icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
	var finite = (value) => typeof value === "number" && Number.isFinite(value);
	var num = (value, digits = 2) => finite(value) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value) : "—";
	var ltr = (value) => `<span class="ltr">${esc(value)}</span>`;
	var dateText = (value) => value ? String(value).replace("T", " ").replace(/\.\d+(?=Z|[+-]\d\d:|$)/, "").replace(/Z$/, " UTC") : "—";
	var timeText = (value) => value ? String(value).replace("T", " ").slice(11, 19) || value : "—";
	var pill = (text, tone = "", dot = true) => `<span class="status-pill ${tone}">${dot ? "<span class=\"dot\"></span>" : ""}${esc(text)}</span>`;
	var empty = (title, description, name = "wave", action = "", compact = false) => `<div class="empty-state ${compact ? "compact" : ""}"><span class="empty-icon">${icon(name)}</span><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
	var startButton = "<button class=\"button primary\" data-action=\"new-session\">بدء جلسة جديدة " + icon("arrow") + "</button>";
	var pages = {
		start: [
			"تعرّف على مورد",
			"الماء يعود نافعًا",
			"افهم الفكرة، جرّب المحطة، وتابع ما يحدث."
		],
		components: [
			"رحلة الماء وأجزاء المحطة",
			"كل جزء، ولماذا نحتاجه",
			"دليل مبسّط للمكونات، مع تفاصيل إضافية لمن يريد."
		],
		technology: [
			"البرمجة والذكاء والأدلة",
			"شفافية يمكن فهمها",
			"كيف يعمل النظام، ما الذي اختبرناه، وما حدود هذه النسخة."
		],
		follow: [
			"المتابعة والسجل",
			"الحالة، ثم السبب، ثم الإجراء",
			"اعرف ما يحدث الآن وراجع أثر التجربة."
		],
		engineering: [
			"مخطط التشغيل التفصيلي",
			"عرض هندسي إضافي",
			"المخطط المبسّط الأصلي؛ المرجع المكاني الأحدث في تجربة المحطة."
		],
		plant: [
			"جرّب المحطة",
			"محاكاة تفاعلية / وحدة مورد",
			"ابدأ التشغيل، جرّب سيناريو، وافهم سبب القرار."
		],
		overview: [
			"نظرة عامة",
			"الماء، بوضوح أكثر",
			"تابع القراءات، وافهم التنبيه، وراجع ما حدث."
		],
		measurements: [
			"القياسات",
			"من المصدر إلى الشاشة",
			"قراءات فعلية من المصدر المحدد، مع الحفاظ على القيم المفقودة."
		],
		alerts: [
			"التنبيهات",
			"افهم سبب الإشارة",
			"راجع التنبيه وسياقه، ثم سجّل اطلاعك عليه."
		],
		history: [
			"السجل والتصدير",
			"أثر يمكن مراجعته",
			"كل قراءة مرتبطة بمصدرها وجلستها وقرار البرنامج."
		],
		model: [
			"مختبر الذكاء",
			"الدليل قبل الادعاء",
			"النموذج البحثي على بياناته العامة، وحدود تأهيله."
		],
		settings: [
			"الإعدادات",
			"ضبط مساحة العمل",
			"حدود تجريبية للقواعد المحلية؛ لا تعدّل نموذج الذكاء الاصطناعي."
		]
	};
	var state = {
		data: null,
		sources: [],
		page: "start",
		connected: false,
		fetching: false,
		mutation: null,
		guideUi: {
			tourStep: 0,
			component: "source"
		},
		plantUi: {
			equipment: "collection",
			zoom: false,
			previousLevels: {},
			reducedMotion: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches === true
		},
		stateGeneration: 0,
		historyRequest: 0,
		historyKey: null,
		alarmsRequest: 0,
		autoplay: false,
		timer: null,
		batch: 10,
		channel: null,
		readings: [],
		historyLoaded: false,
		historyError: "",
		historyScope: "all",
		historyLimit: 100,
		alarms: [],
		alarmsLoaded: false,
		alarmsError: "",
		alarmFilter: "all",
		settingsRendered: false,
		toastTimer: null
	};
	function connection(connected, error) {
		state.connected = connected;
		$("#connection-badge").className = `connection-badge ${connected ? "connected" : "disconnected"}`;
		$("#connection-badge").innerHTML = `<span class="dot"></span><span>${connected ? "الخدمة المحلية متصلة" : "الخدمة غير متصلة"}</span>`;
		$("#connection-error").hidden = connected;
		if (error) $("#connection-error-detail").textContent = error.message;
	}
	function toast(message, error = false) {
		clearTimeout(state.toastTimer);
		const node = $("#toast");
		node.textContent = message;
		node.className = `toast${error ? " error" : ""}`;
		node.hidden = false;
		state.toastTimer = setTimeout(() => {
			node.hidden = true;
		}, error ? 8500 : 4500);
	}
	function applyState(data) {
		if (!data || !data.app || !data.overview || !Array.isArray(data.series)) throw new Error("بنية الحالة غير صالحة. لا توجد بيانات بديلة للعرض.");
		const previousPlant = plantView(state.data), nextPlant = plantView(data);
		state.plantUi.previousLevels = previousPlant.active && previousPlant.sessionId === nextPlant.sessionId ? {
			collection: previousPlant.tanks?.collection?.level_pct,
			treated: previousPlant.tanks?.treated?.level_pct
		} : {};
		state.data = data;
		connection(true);
		state.alarmsRequest++;
		state.alarmsLoaded = false;
		state.alarmsError = "";
		if (state.historyKey !== null && state.historyKey !== historySelectionKey()) {
			state.historyRequest++;
			state.readings = [];
			state.historyLoaded = false;
			state.historyError = "";
		}
		$("#site-label").textContent = data.settings?.site_name || "مساحة التشغيل المحلية";
		$("#research-context").textContent = data.source?.kind === "telemetry" ? "استقبال قراءات عبر API. النموذج غير مؤهل لهذا المخطط، ولا اتصال بصمام فعلي." : data.source?.kind === "digital_twin" ? "قراءات المنشأة الافتراضية من محرك التوأم الرقمي. النموذج البحثي متاح في مختبر الذكاء على مصادره العامة." : "مصادر تاريخية معلنة. لا حساسات ميدانية متصلة، ولا حكم على صلاحية المياه.";
		if (data.source?.kind !== "public_replay" || data.session?.status === "completed" || data.session?.status === "failed") stopAutoplay();
		$("#nav-alert-count").textContent = num(data.overview.unacknowledged_alarms, 0);
		safeLink(data.links?.viewer);
		$("#viewer-link").href = "/plant3d/index.html";
		$("#viewer-link").removeAttribute("target");
		$("#last-updated").textContent = `آخر اتصال بالخدمة: ${(/* @__PURE__ */ new Date()).toLocaleTimeString("ar-SA", {
			hour: "2-digit",
			minute: "2-digit",
			second: "2-digit"
		})}`;
		$("#page-content").setAttribute("aria-busy", "false");
		render();
	}
	async function refresh({ all = false } = {}) {
		if (state.fetching || state.mutation) return;
		const generation = state.stateGeneration;
		state.fetching = true;
		$("#refresh-button").disabled = true;
		try {
			const data = await api.state();
			if (generation !== state.stateGeneration) return;
			applyState(data);
			if (!state.sources.length) {
				const result = await api.sources();
				if (generation !== state.stateGeneration) return;
				if (!Array.isArray(result.sources)) throw new Error("تعذّر قراءة قائمة المصادر من الخدمة.");
				state.sources = result.sources;
			}
			if ((all || state.historyKey !== historySelectionKey()) && state.page === "history") await loadHistory();
			if (state.page === "alerts") await loadAlarms();
		} catch (error) {
			if (generation !== state.stateGeneration) return;
			stopAutoplay();
			connection(false, error);
			render();
		} finally {
			state.fetching = false;
			$("#refresh-button").disabled = false;
		}
	}
	function mutationUI() {
		document.querySelectorAll("[data-auto-start]").forEach((node) => {
			node.disabled ||= presentationStarting || Boolean(state.mutation);
		});
		const busy = $("#experience-busy");
		if (busy) busy.hidden = !state.mutation;
		document.querySelectorAll("[data-mutation]").forEach((node) => {
			node.disabled = Boolean(state.mutation) || !state.connected;
		});
		document.querySelectorAll("[data-plant-control]").forEach((node) => {
			node.disabled = Boolean(state.mutation) || !state.connected || !plantView(state.data).active;
		});
		$("#new-session-button").disabled = Boolean(state.mutation) || !state.connected;
		$("#session-submit").disabled = Boolean(state.mutation) || !state.connected || !$("#research-ack")?.checked;
		if (state.mutation) $("#page-content").setAttribute("aria-busy", "true");
		else $("#page-content").setAttribute("aria-busy", "false");
	}
	async function mutate(task) {
		if (state.mutation) throw new Error("انتظر اكتمال العملية الحالية.");
		const focusedControl = document.activeElement;
		state.stateGeneration++;
		const operation = (async () => {
			try {
				const result = await task();
				applyState(result);
				$("#guide-scene")?.contentWindow?.postMessage({ type: "mawrid:refresh" }, location.origin);
				return result;
			} catch (error) {
				stopAutoplay();
				if (!error.status || error.code === "timeout") connection(false, error);
				throw error;
			}
		})();
		state.mutation = operation;
		mutationUI();
		try {
			return await operation;
		} finally {
			state.mutation = null;
			mutationUI();
			render();
			if (focusedControl?.isConnected && document.activeElement === document.body) focusedControl.focus({ preventScroll: true });
		}
	}
	function stopAutoplay() {
		state.autoplay = false;
		clearTimeout(state.timer);
		state.timer = null;
	}
	async function pause() {
		stopAutoplay();
		render();
		try {
			if (state.mutation) await state.mutation;
			if (state.data?.session?.id && state.data.source?.kind === "public_replay") await mutate(() => api.pause());
		} catch (error) {
			toast(error.message, true);
		}
	}
	async function play() {
		if (state.autoplay || state.mutation || !state.connected) return;
		if (!canReplay()) return;
		state.autoplay = true;
		render();
		async function tick() {
			if (!state.autoplay || !canReplay()) {
				stopAutoplay();
				render();
				return;
			}
			try {
				await mutate(() => api.step(state.batch));
			} catch (error) {
				toast(error.message, true);
				return;
			}
			if (state.autoplay && canReplay()) state.timer = setTimeout(tick, 1e3);
			else {
				stopAutoplay();
				render();
			}
		}
		await tick();
	}
	function canReplay() {
		const s = state.data?.session;
		return state.data?.source?.kind === "public_replay" && s?.id && ![
			"completed",
			"failed",
			"idle"
		].includes(s.status) && s.position < s.total;
	}
	function channels() {
		const source = state.data?.source;
		return source?.channels?.length ? source.channels : state.sources.find((s) => s.id === source?.id)?.channels || [];
	}
	function series() {
		return [...state.data?.series || []].sort((a, b) => a.id - b.id).slice(-60);
	}
	function predictionText(row) {
		if (!row) return {
			text: "بانتظار قراءة",
			tone: "neutral"
		};
		if (row.prediction === 1) return {
			text: "إشارة شذوذ",
			tone: "danger"
		};
		if (row.prediction === 0) return {
			text: "لم يُكتشف شذوذ",
			tone: "good"
		};
		return {
			text: row.ignored_gap ? "تهيئة القراءة" : "الذكاء غير متاح",
			tone: "neutral"
		};
	}
	function sessionBanner() {
		const data = state.data, s = data?.session;
		if (!s?.id) return "";
		if (data.source?.kind === "digital_twin") return `<section class="session-banner"><span class="session-icon">${icon("box")}</span><div class="session-details"><strong>توأم رقمي · منشأة افتراضية</strong><small>قراءات محاكاة من غرفة التشغيل، دون تشغيل نموذج على هذا المصدر.</small></div><a class="button small" href="#plant">غرفة التشغيل ${icon("arrow")}</a></section>`;
		if (!["telemetry", "public_replay"].includes(data.source?.kind)) return "";
		const telemetry = data.source?.kind === "telemetry";
		const labels = {
			idle: "غير مبدوءة",
			ready: state.autoplay ? "تشغيل إعادة العرض" : "جاهزة للقراءة",
			paused: "متوقفة مؤقتًا",
			completed: "اكتملت البيانات",
			failed: "توقفت بخطأ"
		};
		const progress = finite(s.total) && s.total > 0 ? Math.max(0, Math.min(100, s.position / s.total * 100)) : 0;
		return `<section class="session-banner ${s.status === "completed" ? "session-ended" : ""}" aria-label="الجلسة الحالية"><span class="session-icon">${icon(telemetry ? "server" : "wave")}</span><div class="session-details"><strong>${esc(data.source?.name || "الجلسة الحالية")} ${pill(telemetry ? "استقبال API" : labels[s.status] || s.status, s.status === "failed" ? "danger" : "good")}</strong><small>${telemetry ? "بيانات مرسلة عبر API؛ لا يدعم النموذج البحثي هذا المخطط." : `أعيد عرض ${num(s.position, 0)} من ${num(s.total, 0)} قراءة · فاصل المصدر ${num(s.sample_seconds, 0)} ثانية`}</small>${!telemetry ? `<div class="session-progress" role="progressbar" aria-label="تقدم إعادة العرض" aria-valuenow="${progress.toFixed(1)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${progress}%"></span></div>` : ""}</div><div class="session-controls">${telemetry ? "<button class=\"button small\" data-action=\"telemetry-help\">طريقة إرسال القراءات</button>" : `<label class="sr-only" for="batch-size">عدد القراءات في كل دفعة</label><select class="field-select" id="batch-size" aria-label="عدد القراءات في كل دفعة" ${state.autoplay ? "disabled" : ""}>${[
			1,
			5,
			10,
			25
		].map((n) => `<option value="${n}" ${state.batch === n ? "selected" : ""}>${n} ${n === 1 ? "قراءة" : "قراءات"} / دفعة</option>`).join("")}</select><button class="button small" data-action="step" data-mutation ${!canReplay() || state.autoplay ? "disabled" : ""}>${icon("step")}قراءة واحدة</button><button class="button small primary" data-action="${state.autoplay ? "pause" : "play"}" ${!canReplay() && !state.autoplay ? "disabled" : ""}>${icon(state.autoplay ? "pause" : "play")}${state.autoplay ? "إيقاف مؤقت" : "تشغيل"}</button>`}</div></section>`;
	}
	function statCard(title, value, note, name, small = false) {
		return `<article class="stat-card"><div class="stat-top"><span>${esc(title)}</span><span class="stat-icon">${icon(name)}</span></div><div class="stat-value ${small ? "small-value" : ""}">${esc(value)}</div><div class="stat-note">${esc(note)}</div></article>`;
	}
	function stats() {
		const d = state.data, latest = d?.latest, pred = predictionText(latest);
		return `<div class="stats-grid">${statCard("القراءات في الجلسة", num(d?.overview?.readings, 0), "من المصدر المختار، كما حُفظت", "wave")}${statCard("تنبيهات تحتاج مراجعة", num(d?.overview?.unacknowledged_alarms, 0), "المراجعة توثّق الاطلاع ولا تلغي السبب", "bell")}${statCard("آخر إشارة للنموذج", pred.text, "ليست حكمًا على سلامة المياه", "brain", true)}${statCard("صمام البرنامج", d ? "مغلق" : "—", "حالة برمجية فقط · لا جهاز متصل", "shield", true)}</div>`;
	}
	function chartPanel() {
		const available = channels(), rows = series();
		if (!available.some((c) => c.key === state.channel)) state.channel = available[0]?.key || null;
		const channel = available.find((c) => c.key === state.channel);
		const chart = channel ? sensorChart(rows, channel) : null;
		return `<section class="panel"><div class="panel-heading"><div><h2>مسار القراءات</h2><p>آخر ${rows.length || "—"} قراءة محفوظة · ساعة المصدر الأصلية</p></div>${available.length ? `<div class="chart-controls"><select class="field-select" id="chart-channel" aria-label="الحساس المعروض في الرسم">${available.map((c) => `<option value="${esc(c.key)}" ${c.key === state.channel ? "selected" : ""}>${esc(c.name)}${c.unit ? " · " + esc(c.unit) : ""}</option>`).join("")}</select></div>` : ""}</div>${chart?.svg ? `<div class="chart-area">${chart.svg}</div><div class="chart-summary"><span>أقل قراءة<strong>${ltr(num(chart.min, 4))}</strong></span><span>أعلى قراءة<strong>${ltr(num(chart.max, 4))}</strong></span><span>الوحدة<strong>${esc(channel.unit || "غير محددة")}</strong></span></div><div class="chart-legend"><span><i class="legend-dot"></i>قياس المصدر</span><span><i class="legend-dot alert"></i>إشارة شذوذ من النموذج</span></div>${chart.missingCount ? `<div class="chart-missing">${chart.missingCount} قراءة مفقودة؛ يظهر انقطاع في الخط دون تعويضها.</div>` : ""}` : empty("لم تصل قراءات للرسم بعد", state.data?.session?.id ? "شغّل إعادة العرض، أو أرسل قراءة إلى جلسة API الحالية." : "ابدأ جلسة من مصدر متاح لعرض المسار الفعلي.", "wave", "", true)}</section>`;
	}
	function sensorCards() {
		const available = channels(), latest = state.data?.latest;
		if (!available.length) return empty("لا مصدر محدد", "ستظهر الحساسات ووحداتها بعد بدء الجلسة.", "droplet", "", true);
		return `<div class="sensor-grid">${available.map((c) => {
			const value = latest?.channels?.[c.key], missing = !finite(value);
			return `<article class="sensor-card ${missing ? "missing" : ""}"><div class="sensor-name"><span>${esc(c.name)}</span><span class="sensor-code">${esc(c.key)}</span></div><div class="sensor-value"><strong>${num(value, 4)}</strong><small>${esc(c.unit || "")}</small></div><div class="sensor-foot">${!latest ? "بانتظار أول قراءة" : missing ? "القيمة مفقودة في قراءة المصدر" : "قيمة المصدر الأصلية · " + esc(timeText(latest.timestamp))}</div></article>`;
		}).join("")}</div>`;
	}
	function decisionPanel() {
		const d = state.data, row = d?.latest, pred = predictionText(row);
		return `<section class="panel"><div class="panel-heading"><h2>إشارة النموذج والقرار</h2>${pill(d?.model?.version || "غير محمّل", "neutral", false)}</div><div class="decision-box ${pred.tone === "danger" ? "danger" : ""}"><span class="decision-symbol">${icon(row?.prediction === 1 ? "bell" : "shield")}</span><div><h3>${esc(pred.text)}</h3><p>${!row ? "تظهر الإشارة بعد قراءة البيانات وتهيئة السياق." : row.prediction === 1 ? "يستدعي اختلاف القراءة أو نمطها المراجعة؛ لا يحدد نوع العطل." : row.prediction === 0 ? "لم يرفع النموذج إشارة لهذه القراءة. لا يعني هذا أن المياه آمنة." : row.ignored_gap ? "هذه القراءة ضمن الجزء المستبعد قبل التهيئة." : "السياق غير كافٍ أو المخطط غير مؤهل لهذا النموذج."}</p></div></div><ul class="decision-list"><li><span>درجة ترتيب الشذوذ</span><strong>${ltr(num(row?.score, 5))}</strong></li><li><span>القرار البرمجي</span><strong>${esc(d?.overview?.decision || "بانتظار بيانات")}</strong></li><li><span>حالة صمام البرنامج</span><strong>${d ? "مغلق — دون عتاد" : "غير متاحة"}</strong></li><li><span>لترات ري مقاسة</span><strong>${finite(d?.overview?.measured_irrigation_liters) ? num(d.overview.measured_irrigation_liters) + " لتر" : "غير مقاسة"}</strong></li></ul>${d?.overview?.reasons?.length ? `<ul class="reason-notes">${d.overview.reasons.map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul>` : ""}<div class="panel-footer">الدرجة ليست احتمال سلامة ولا «ثقة حساس». الذكاء لا يفتح صمامًا.</div></section>`;
	}
	function alertPreview() {
		const alerts = state.data?.alarms?.slice(0, 4) || [];
		return `<section class="panel"><div class="panel-heading"><div><h2>آخر التنبيهات</h2><p>السبب قبل الإجراء</p></div><a class="text-button" href="#alerts">عرض الكل ${icon("arrow")}</a></div>${alerts.length ? `<div style="padding-block:10px">${alerts.map((a) => `<div class="recent-event"><span class="event-indicator ${a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : ""}"></span><div class="event-copy"><strong>${esc(a.title)}</strong><p>${esc(a.detail)}</p></div><time title="${esc(dateText(a.timestamp))}">${esc(timeText(a.timestamp))}</time></div>`).join("")}</div>` : empty("لا تنبيهات مسجلة للعرض", state.data?.session?.id ? "ستظهر إشارات النموذج أو القواعد هنا عند وصولها." : "ابدأ جلسة أولًا. عدم وجود تنبيه لا يثبت سلامة المياه.", "bell", "", true)}</section>`;
	}
	function overview() {
		const noSession = !state.data?.session?.id;
		return `${sessionBanner()}${stats()}<div class="dashboard-grid">${noSession ? `<section class="panel start-panel"><div><span class="eyebrow">ابدأ من بيانات تعرف مصدرها</span><h2>قراءة أوضح.<br>قرار يمكن مراجعته.</h2><p>أعد عرض بيانات GECCO أو WaterHub التاريخية، وشاهد استدلال النموذج الحقيقي وسجل كل إشارة.</p>${startButton}</div><span class="start-mark">${icon("droplet")}</span></section>` : chartPanel()}${decisionPanel()}<section class="panel"><div class="panel-heading"><div><h2>الحساسات</h2><p>${esc(state.data?.source?.name || "القيم غير متاحة حتى اختيار المصدر")}</p></div><a class="text-button" href="#measurements">كل القياسات ${icon("arrow")}</a></div>${sensorCards()}</section>${alertPreview()}<section class="panel full-width"><div class="panel-heading"><h2>من القراءة إلى سجل قابل للمراجعة</h2>${pill("مسار البرنامج", "neutral", false)}</div><div class="process-track">${[
			[
				"server",
				"مصدر معلن",
				"تاريخي أو API"
			],
			[
				"wave",
				"قراءة أصلية",
				"دون ملء القيم"
			],
			[
				"brain",
				"تحليل بحثي",
				"عند توفر السياق"
			],
			[
				"shield",
				"قرار محجوز",
				"لا فتح فعلي"
			],
			[
				"list",
				"سجل وتصدير",
				"مع مصدر القراءة"
			]
		].map(([i, t, s]) => `<div class="process-node"><span>${icon(i)}</span><div>${t}<small>${s}</small></div></div>`).join("")}</div></section></div>`;
	}
	function measurements() {
		return `${sessionBanner()}<section class="panel"><div class="panel-heading"><div><h2>آخر قياس لكل قناة</h2><p>${state.data?.latest ? "وقت المصدر: " + esc(dateText(state.data.latest.timestamp)) : "بانتظار قراءة من المصدر المختار"}</p></div>${pill(state.data?.source?.kind === "telemetry" ? "API · دون تأهيل ML" : state.data?.source?.kind === "digital_twin" ? "قراءات المنشأة الافتراضية" : "إعادة عرض تاريخية", "neutral")}</div>${sensorCards()}</section><div class="dashboard-grid">${chartPanel()}${decisionPanel()}</div><div class="info-callout section-spacer">${icon("info")}<p>الضغط والموصلية والعكارة قنوات مختلفة بوحداتها الأصلية. لا نستنتج الكلور من ORP أو من قناة أخرى، ولا نحول قيمة مفقودة إلى صفر.</p></div>`;
	}
	var alarmKinds = {
		anomaly: "إشارة النموذج",
		missing: "قراءة مفقودة",
		safety: "قاعدة تجريبية",
		system: "النظام"
	};
	function alertsPage() {
		const all = state.alarmsLoaded ? state.alarms : state.data?.alarms || [];
		const rows = all.filter((a) => state.alarmFilter === "all" || (state.alarmFilter === "open" ? !a.acknowledged_at : !!a.acknowledged_at));
		return `<section class="panel"><div class="toolbar"><div class="filter-chips" aria-label="تصفية التنبيهات">${[
			["all", "الكل"],
			["open", "لم تُراجع"],
			["reviewed", "تمت مراجعتها"]
		].map(([key, label]) => `<button class="filter-chip ${state.alarmFilter === key ? "active" : ""}" data-filter="${key}" aria-pressed="${state.alarmFilter === key}">${label}</button>`).join("")}</div><span class="muted" style="font-size:10px">${all.length} تنبيه محمّل · حتى 100</span><div class="toolbar-end"><button class="button small" data-action="refresh-alarms">${icon("refresh")}تحديث</button><button class="button small" data-action="export-events">${icon("download")}تصدير جميع الأحداث</button></div></div>${state.alarmsError ? `<p class="form-error" style="margin:18px">${esc(state.alarmsError)}</p>` : ""}${rows.length ? `<div class="alert-list">${rows.map((a) => `<article class="alert-card ${a.severity === "critical" ? "danger" : a.severity === "warning" ? "warning" : ""}"><span class="event-indicator ${a.severity === "critical" ? "danger" : "warning"}"></span><div class="event-copy"><strong>${esc(a.title)}</strong><p>${esc(a.detail)}</p><div class="alert-meta"><span>${esc(alarmKinds[a.kind] || a.kind)}</span><time class="ltr">${esc(dateText(a.timestamp))}</time><span>رقم ${esc(a.id)}</span></div>${a.acknowledged_at ? `<p>تمت المراجعة: ${ltr(dateText(a.acknowledged_at))}</p>` : ""}</div>${a.acknowledged_at ? pill("تم الاطلاع", "good") : `<button class="button small" data-action="ack" data-id="${esc(a.id)}" data-mutation>${icon("check")}تم الاطلاع</button>`}</article>`).join("")}</div>` : empty("لا تنبيهات ضمن هذا العرض", "المراجعة تسجل اطلاعك فقط؛ لا تمسح الحدث ولا تؤكد زوال سببه.", "bell")}<div class="panel-footer">المعروض من السجل الدائم عبر الجلسات. توجد كل الأحداث في ملف التصدير.</div></section>`;
	}
	function historyPage() {
		const rows = state.readings;
		return `<section class="panel"><div class="toolbar"><label class="field"><span class="sr-only">نطاق السجل</span><select id="history-scope" class="field-select"><option value="all" ${state.historyScope === "all" ? "selected" : ""}>كل الجلسات</option><option value="current" ${state.historyScope === "current" ? "selected" : ""} ${!state.data?.session?.id ? "disabled" : ""}>الجلسة الحالية</option></select></label><label class="field"><span class="sr-only">عدد القراءات</span><select id="history-limit" class="field-select">${[
			100,
			250,
			1e3
		].map((n) => `<option value="${n}" ${n === state.historyLimit ? "selected" : ""}>آخر ${n} قراءة</option>`).join("")}</select></label><div class="toolbar-end"><button class="button small" data-action="refresh-history">${icon("refresh")}تحديث</button><button class="button small" data-action="export-readings">${icon("download")}كل القراءات CSV</button><button class="button small" data-action="export-report">${icon("list")}ملخص JSON</button></div></div>${state.historyError ? `<p class="form-error" style="margin:18px">${esc(state.historyError)}</p>` : ""}${!state.historyLoaded && !state.historyError ? "<div class=\"loading-block\"><div class=\"loading-line\"></div>جارٍ قراءة السجل…</div>" : rows.length ? `<div class="table-scroll"><table><thead><tr><th>القراءة</th><th>وقت المصدر</th><th>المصدر / الجلسة</th><th>القنوات</th><th>إشارة النموذج</th><th>الدرجة</th><th>القرار والسبب</th></tr></thead><tbody>${rows.map((row) => {
			const p = predictionText(row);
			return `<tr><td>${esc(row.id)}<small class="sensor-foot" style="display:block">#${esc(row.sample_index ?? "—")}</small></td><td class="time">${esc(dateText(row.timestamp))}</td><td>${ltr(row.source_id || "—")}<small class="sensor-foot" style="display:block">${ltr((row.session_id || "").slice(0, 8))}</small></td><td class="reason">${Object.entries(row.channels || {}).map(([key, value]) => `${ltr(key)}: ${ltr(num(value, 4))}`).join(" · ")}</td><td>${pill(p.text, p.tone)}</td><td>${ltr(num(row.score, 5))}</td><td class="reason"><strong>${esc(row.decision || "—")}</strong><br>${esc((row.reasons || []).join(" · "))}</td></tr>`;
		}).join("")}</tbody></table></div><div class="pagination"><span>${rows.length} قراءة معروضة</span><span>ملف CSV يشمل كل السجل المحفوظ</span></div>` : empty("السجل فارغ", "ستُحفظ القراءات الفعلية أثناء إعادة العرض أو استقبال API، دون حذف الجلسات السابقة.", "list")}<div class="panel-footer">السجل يصف قراءات البرنامج، وليس شهادة امتثال أو تقرير توفير مياه. قد تختلف ساعة المصدر عن وقت الاستقبال.</div></section>`;
	}
	function modelPage() {
		const model = state.data?.model, metrics = model?.metrics || {}, report = safeLink(state.data?.links?.model_report);
		return `<section class="model-hero"><span class="model-icon">${icon("brain")}</span><div><h2>كشف الشذوذ · ${esc(model?.version || "بانتظار الخدمة")}</h2><p>${esc(model?.message || "ستظهر هوية النموذج وحدود تأهيله من الخدمة المحلية.")}</p></div>${pill(model?.status === "unavailable" ? "غير مؤهل للمصدر" : model?.status === "not_loaded" ? "غير محمّل" : "بحثي فقط", "neutral")}</section><div class="stats-grid section-spacer">${statCard("أحداث مكتشفة في التطوير", finite(metrics.events_detected) ? `${metrics.events_detected} من ${metrics.events_total}` : "—", "مقياس الحدث؛ لا تمثله دقة القراءات", "wave", true)}${statCard("مقاطع إنذار كاذب", num(metrics.false_alarm_fragments, 0), "على كامل فترات التطوير", "bell")}${statCard("دقائق إنذار كاذب", num(metrics.false_alarm_minutes, 0), "مدة الإنذار، لا عدد المقاطع", "clock")}${statCard("فترات الاختبار", num(metrics.periods, 0), "فترات زمنية معلنة ومستخدمة في التطوير", "list")}</div><div class="dashboard-grid"><section class="panel"><div class="panel-heading"><h2>التأهيل وحدود التشغيل</h2></div><div class="panel-body"><dl class="definition-list"><div><dt>الإصدار المستخدم</dt><dd>${esc(model?.version || "—")}</dd></div><div><dt>القبول الإحصائي</dt><dd>${model ? model.acceptance_passed ? "بحسب دليل الخدمة" : "لم يجتز معيار القبول" : "غير متاح"}</dd></div><div><dt>المصادر البحثية</dt><dd>GECCO · WaterHub</dd></div><div><dt>الحساسات الميدانية</dt><dd>لا توجد تجربة ميدانية مثبتة</dd></div><div><dt>فتح الصمام بالذكاء</dt><dd>غير متاح</dd></div><div><dt>إصدار تلقائي جديد</dt><dd>لا ترقية صامتة</dd></div></dl><div class="info-callout section-spacer">${icon("info")}<p>${esc(model?.qualification || "لا معلومات تأهيل متاحة بعد.")}</p></div>${report ? `<a class="button section-spacer" href="${esc(report)}" target="_blank" rel="noopener">${icon("external")}افتح تقرير التقييم الكامل</a>` : ""}</div></section><section class="panel"><div class="panel-heading"><h2>ما تعنيه الإشارة</h2></div><div class="panel-body"><ul class="limit-list">${(model?.limitations || ["لا يمكن تقييم صلاحية الماء من إشارة النموذج وحدها.", "لا توجد نتائج نموذج متاحة حتى تتصل الخدمة المحلية."]).map((text) => `<li>${icon("shield")}<div>${esc(text)}</div></li>`).join("")}</ul></div></section></div><div class="info-callout warning section-spacer">${icon("info")}<p><strong>التطبيق قابل للتشغيل، والنموذج ما زال بحثيًا.</strong> نجاح استدعاء النموذج أو تطابق درجاته برمجيًا لا يثبت جودة مياه الوضوء، ولا تصنيف الأعطال الخمسة، ولا زمن الاستجابة على Raspberry Pi. التنبؤ بالطلب والمساعد العربي مرحلتان لاحقتان.</p></div>`;
	}
	var settingsFields = [
		[
			"turbidity_max",
			"أعلى عكارة تجريبية",
			"NTU",
			"0.01",
			0,
			1e3
		],
		[
			"ph_min",
			"أقل pH تجريبي",
			"pH",
			"0.1",
			0,
			14
		],
		[
			"ph_max",
			"أعلى pH تجريبي",
			"pH",
			"0.1",
			0,
			14
		],
		[
			"chlorine_min",
			"أقل كلور متبقٍ تجريبي",
			"mg/L",
			"0.01",
			0,
			20
		],
		[
			"chlorine_max",
			"أعلى كلور متبقٍ تجريبي",
			"mg/L",
			"0.01",
			0,
			20
		],
		[
			"stale_seconds",
			"مهلة تقادم قراءة الجهاز",
			"ثانية",
			"1",
			1,
			86400
		]
	];
	function telemetryView(data) {
		const session = data?.session, telemetry = data?.telemetry;
		if (!(data?.source?.kind === "telemetry" && typeof session?.id === "string" && session.id.length > 0 && ["ready", "paused"].includes(session.status) && telemetry?.session_id === session.id)) return {
			eligible: false,
			sessionId: null,
			lastDeviceId: null,
			lastReceivedAt: null,
			receipt: null
		};
		const text = (value) => typeof value === "string" && value.length > 0 ? value : null;
		const receipt = telemetry.last_receipt;
		return {
			eligible: true,
			sessionId: session.id,
			lastDeviceId: text(telemetry.last_device_id),
			lastReceivedAt: text(telemetry.last_received_at),
			receipt: receipt?.session_id === session.id && text(receipt.measurement_id) && Number.isSafeInteger(receipt.reading_id) && receipt.reading_id > 0 ? {
				measurementId: receipt.measurement_id,
				readingId: receipt.reading_id
			} : null
		};
	}
	function telemetryCardContent() {
		const view = telemetryView(state.data);
		return `<div class="panel-heading"><div><h2>ربط جامع القراءات</h2><p>اختبار الاستقبال البرمجي على هذا الجهاز</p></div>${pill(!view.eligible ? "لا جلسة API جاهزة" : view.lastReceivedAt ? "وصلت قراءة" : "بانتظار أول قراءة", "neutral")}</div><div class="panel-body">${view.eligible ? `<p class="settings-note">ثبّت هذا المعرّف في إعداد الجامع. بدء جلسة أخرى يستلزم اختيارها صراحة؛ لا تنتقل القراءات تلقائيًا إلى جلسة إعادة عرض.</p><div class="telemetry-session"><span>معرّف جلسة API</span><code dir="ltr">${esc(view.sessionId)}</code><button type="button" class="button small" data-action="copy-telemetry-session" data-mutation ${!state.connected || state.mutation ? "disabled" : ""}>نسخ معرّف الجلسة</button></div><dl class="telemetry-details"><div><dt>آخر جهاز أرسل</dt><dd>${view.lastDeviceId ? ltr(view.lastDeviceId) : "لم يصل معرّف جهاز"}</dd></div><div><dt>آخر استلام لدى الخادم</dt><dd>${view.lastReceivedAt ? ltr(dateText(view.lastReceivedAt)) : "لم تصل قراءة بعد"}</dd></div><div><dt>إيصال آخر قراءة</dt><dd>${view.receipt ? `${ltr(view.receipt.measurementId)}<small>رقم القراءة المحفوظة: ${ltr(view.receipt.readingId)}</small>` : view.lastReceivedAt ? "لا يوجد إيصال مرقّم لهذه القراءة" : "لم يصل إيصال بعد"}</dd></div></dl>${!state.connected ? "<p class=\"form-error\">الخدمة غير متصلة؛ المعروض آخر حالة مستلمة. حدّث الاتصال قبل نسخ المعرّف.</p>" : ""}` : `<p class="settings-note">ابدأ جلسة «قراءات جهاز عبر API» قبل إعداد الجامع. معرّف جلسة إعادة العرض لا يصلح لاستقبال قياسات الجهاز، ولن يُستخدم بدلًا منها.</p><button type="button" class="button section-spacer" data-action="telemetry-session" data-mutation>اختيار جلسة API جديدة ${icon("arrow")}</button>`}<p class="settings-note section-spacer">يرسل جامع JSONL قراءة محفوظة في كل سطر إلى الجلسة المحددة. اتبع دليل الجامع المحلي لصيغة الملف وطريقة التشغيل؛ لا تُرسل هذه البطاقة أي قياسات.</p><div class="info-callout section-spacer">${icon("info")}<p>وصول قراءة أو إيصال يثبت الاستلام البرمجي فقط، ولا يثبت اتصال حساس أو صحة قياسه. نموذج V9 البحثي غير مؤهل لهذا المخطط؛ القواعد التجريبية فقط مفعّلة، وصمام البرنامج مغلق دون أوامر لعتاد.</p></div></div>`;
	}
	function updateTelemetryCard() {
		const card = $("#telemetry-card");
		if (!card) return;
		const html = telemetryCardContent();
		if (card.telemetryMarkup !== html) {
			const focused = document.activeElement?.closest?.("#telemetry-card [data-action]")?.dataset.action;
			card.innerHTML = html;
			card.telemetryMarkup = html;
			if (["copy-telemetry-session", "telemetry-session"].includes(focused)) $(`#telemetry-card [data-action="${focused}"]`)?.focus({ preventScroll: true });
		}
	}
	async function copyTelemetrySession() {
		const view = telemetryView(state.data);
		if (!view.eligible || !state.connected || state.mutation) throw new Error("لا توجد جلسة API حالية جاهزة للنسخ. حدّث الحالة أولًا.");
		if (!globalThis.navigator?.clipboard?.writeText) throw new Error("النسخ التلقائي غير متاح. حدّد معرّف الجلسة الظاهر وانسخه يدويًا.");
		try {
			await navigator.clipboard.writeText(view.sessionId);
		} catch {
			throw new Error("تعذّر النسخ إلى الحافظة. حدّد معرّف الجلسة الظاهر وانسخه يدويًا.");
		}
		const current = telemetryView(state.data);
		if (!current.eligible || current.sessionId !== view.sessionId || !state.connected) throw new Error("تغيّرت حالة الجلسة أثناء النسخ؛ لا تستخدم المعرّف المنسوخ حتى تحدّث الحالة وتنسخ الجلسة الحالية.");
		toast("نُسخ معرّف جلسة API الحالية.");
	}
	function settingsPage() {
		const settings = state.data?.settings;
		if (!settings) return `<section class="panel">${empty("الإعدادات غير متاحة", "يلزم الاتصال بالخدمة المحلية لقراءة الإعدادات الحالية؛ لن نعرض حدودًا بديلة.", "settings")}</section>`;
		return `<div class="settings-grid"><section class="panel"><div class="panel-heading"><div><h2>إعدادات القواعد التجريبية</h2><p>تُحفظ محليًا وتُراجع من الخادم</p></div>${pill("غير معتمدة تنظيميًا", "warning", false)}</div><form class="panel-body" id="settings-form"><label class="field" style="margin-bottom:22px"><span>اسم الموقع / مساحة العمل</span><input name="site_name" maxlength="100" value="${esc(settings.site_name)}" required autocomplete="off"></label><div class="settings-fields">${settingsFields.map(([key, label, unit, step, min, max]) => `<label class="field"><span>${label} <small class="ltr">${unit}</small></span><input name="${key}" type="number" step="${step}" min="${min}" max="${max}" value="${esc(settings[key])}" required><small>الحد الحالي: ${esc(settings[key])} ${unit}</small></label>`).join("")}</div><p class="form-error" id="settings-error" role="alert" hidden></p><div class="settings-actions"><button class="button primary" type="submit" data-mutation>${icon("check")}حفظ الإعدادات</button><button class="button" type="button" data-action="reload-settings">إلغاء التعديلات</button><p class="settings-note">لا تتغير عتبات ML أو نماذجه.<br>القواعد تخص مخطط قراءات الجهاز.</p></div></form></section><div><section class="panel"><div class="panel-heading"><h2>الاحتجاز البرمجي</h2>${pill("مغلق", "neutral")}</div><div class="panel-body"><p class="settings-note">يمكنك تثبيت احتجاز يدوي أو إزالة هذا الطلب. إزالة الاحتجاز <strong>لا تفتح الصمام</strong>؛ لا يوجد متحكم أمان مؤهل أو عتاد موصول بهذا التطبيق.</p><div class="settings-actions"><button class="button danger" data-action="hold" data-mutation>${icon("shield")}تثبيت الاحتجاز</button><button class="button" data-action="reset" data-mutation>إزالة الطلب اليدوي</button></div></div></section><section class="panel section-spacer" id="telemetry-card" aria-label="ربط جامع القراءات">${telemetryCardContent()}</section></div></div>`;
	}
	function render(force = false) {
		const focusedPresentation = document.activeElement?.dataset?.action;
		reconcilePresentation();
		if (state.page === "settings" && state.settingsRendered && !force) {
			updateTelemetryCard();
			mutationUI();
			return;
		}
		const content = $("#page-content");
		if (GUIDE_PAGES.includes(state.page)) renderGuide(content, state.page, state.data, state.guideUi, state.connected, Boolean(state.mutation), force);
		else if (!state.data && state.connected === false && !$("#connection-error").hidden) content.innerHTML = `<section class="panel">${empty("لا توجد بيانات متاحة الآن", "عند تعذّر الاتصال لا يستبدل التطبيق القراءات ببيانات مولّدة. شغّل الخدمة المحلية ثم أعد المحاولة.", "server", "<button class=\"button primary\" data-action=\"retry\">إعادة الاتصال</button>")}</section>`;
		else if (state.page === "engineering") {
			delete content.dataset.guidePage;
			if (force) content.innerHTML = plantPage(state.data, state.plantUi, Boolean(state.mutation) || !state.connected);
			else updatePlant(content, state.data, state.plantUi, Boolean(state.mutation) || !state.connected);
			state.plantUi.previousLevels = {};
		} else {
			delete content.dataset.guidePage;
			content.innerHTML = {
				overview,
				measurements,
				alerts: alertsPage,
				history: historyPage,
				model: modelPage,
				settings: settingsPage
			}[state.page]();
		}
		if (state.page === "settings" && state.data?.settings) state.settingsRendered = true;
		syncJourneyScene(force);
		updatePresentationClock();
		mutationUI();
		if (["auto-pause", "auto-resume"].includes(focusedPresentation) && document.activeElement === document.body) ($("#page-content [data-action=\"" + focusedPresentation + "\"]") || $("#page-content [data-action=\"auto-start\"]"))?.focus({ preventScroll: true });
		const step = $("[data-action=\"step\"]");
		if (step) step.disabled ||= !canReplay() || state.autoplay;
	}
	function route() {
		const page = location.hash.slice(1);
		state.page = Object.hasOwn(pages, page) ? page : "start";
		document.body.dataset.experience = String(state.page === "plant");
		const [title, eyebrow, description] = pages[state.page];
		$("#page-title").textContent = title;
		$("#breadcrumb-current").textContent = title;
		$("#page-eyebrow").textContent = eyebrow;
		$("#page-description").textContent = description;
		$(".research-strip").hidden = GUIDE_PAGES.includes(state.page) || state.page === "engineering";
		$("#new-session-button").hidden = GUIDE_PAGES.includes(state.page) || state.page === "engineering";
		$("#export-top").hidden = GUIDE_PAGES.includes(state.page) || state.page === "engineering";
		$("#advanced-navigation").open ||= !GUIDE_PAGES.includes(state.page);
		document.title = `${title} | مورد`;
		document.querySelectorAll("[data-page]").forEach((node) => {
			const active = node.dataset.page === state.page;
			node.classList.toggle("active", active);
			if (active) node.setAttribute("aria-current", "page");
			else node.removeAttribute("aria-current");
		});
		state.settingsRendered = false;
		closeMenu();
		render(true);
		$("#main-content").focus({ preventScroll: true });
		window.scrollTo({
			top: 0,
			behavior: "instant"
		});
		if (state.page === "history" && state.connected) loadHistory();
		if (state.page === "alerts" && state.connected) loadAlarms();
	}
	function historySelectionKey() {
		return JSON.stringify([
			state.historyScope,
			state.historyLimit,
			state.historyScope === "current" ? state.data?.session?.id || null : null
		]);
	}
	async function loadHistory() {
		const request = ++state.historyRequest, key = historySelectionKey();
		const sessionId = state.historyScope === "current" ? state.data?.session?.id : void 0;
		const current = () => request === state.historyRequest && key === historySelectionKey();
		state.historyError = "";
		if (key !== state.historyKey) {
			state.readings = [];
			state.historyLoaded = false;
			state.historyKey = key;
		}
		if (state.page === "history") render();
		try {
			if (state.historyScope === "current" && !sessionId) throw new Error("لا توجد جلسة حالية لعرض سجلها. اختر كل الجلسات أو ابدأ جلسة جديدة.");
			const result = await api.readings({
				limit: state.historyLimit,
				sessionId
			});
			if (!current()) return;
			if (!Array.isArray(result.readings)) throw new Error("وصل سجل قراءات غير صالح.");
			state.readings = result.readings;
			state.historyLoaded = true;
		} catch (error) {
			if (current()) state.historyError = error.message;
		}
		if (current() && state.page === "history") render();
	}
	async function loadAlarms() {
		const request = ++state.alarmsRequest, generation = state.stateGeneration;
		const current = () => request === state.alarmsRequest && generation === state.stateGeneration;
		state.alarmsError = "";
		try {
			const result = await api.alarms();
			if (!current()) return;
			if (!Array.isArray(result.alarms)) throw new Error("وصل سجل تنبيهات غير صالح.");
			state.alarms = result.alarms;
			state.alarmsLoaded = true;
		} catch (error) {
			if (current()) state.alarmsError = error.message;
		}
		if (current() && state.page === "alerts") render();
	}
	function sessionFields(sourceId) {
		const source = state.sources.find((s) => s.id === sourceId) || state.sources[0];
		if (!source) {
			$("#session-form-fields").innerHTML = "<p class=\"form-error\">لا توجد مصادر متاحة من الخدمة. أعد الاتصال ثم حاول مجددًا.</p>";
			mutationUI();
			return;
		}
		const copy = {
			telemetry: {
				description: "جلسة استقبال لقياساتك عبر API. لا توجد قراءات تلقائية، ولا ذكاء مؤهل لهذا المخطط؛ حالة الصمام برمجية مغلقة.",
				acknowledgement: "أفهم أن هذه واجهة اختبار محلية دون عتاد أمان أو تأهيل للنموذج على قراءات جهازي."
			},
			public_replay: {
				description: `إعادة عرض ${num(source.rows, 0)} قراءة تاريخية، بفاصل مصدر قدره ${num(source.sample_seconds, 0)} ثانية. يُحسب الاستدلال فعليًا؛ سرعة العرض لا تعني سرعة الحساس.`,
				acknowledgement: "أفهم أن هذا نموذج بحثي على بيانات تاريخية، لم يُعتمد لسلامة مياه الوضوء أو تشغيل صمام فعلي."
			},
			digital_twin: {
				description: "منشأة افتراضية يحسب محركها الخزانات والتدفقات وحالة المعدات بقواعد تشغيل ثابتة. تتقدم ساعة المحاكاة بنبضة أساسية كل ثانية، بسرعة ×1 أو ×10 أو ×30؛ لا يشغّل هذا المصدر نموذج كشف الشذوذ.",
				acknowledgement: "أفهم أنني أبدأ توأمًا رقميًا؛ قراءاته وأحجامه ناتجة عن محاكاة برمجية، ولا يرسل أوامر إلى عتاد فعلي."
			}
		}[source.kind];
		if (!copy) {
			$("#session-form-fields").innerHTML = "<p class=\"form-error\">نوع المصدر غير مدعوم. حدّث قائمة المصادر قبل بدء جلسة.</p>";
			mutationUI();
			return;
		}
		$("#session-form-fields").innerHTML = `<label class="field"><span>مصدر القراءات</span><select id="session-source" required>${state.sources.map((s) => `<option value="${esc(s.id)}" ${s.id === source.id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label><div class="source-description">${esc(copy.description)}<br><span class="muted">${(source.channels || []).map((c) => esc(c.name)).join(" · ")}</span></div><label class="acknowledgement"><input type="checkbox" id="research-ack" required><span>${esc(copy.acknowledgement)}</span></label><p class="settings-note">تُنشأ جلسة جديدة؛ تبقى الجلسات والقراءات السابقة محفوظة في السجل.</p>`;
		mutationUI();
	}
	async function openSession(sourceId) {
		stopAutoplay();
		render();
		$("#session-error").hidden = true;
		if (!state.connected) {
			toast("اتصل بالخدمة المحلية أولًا.", true);
			return;
		}
		if (!state.sources.length) try {
			state.sources = (await api.sources()).sources;
		} catch (error) {
			toast(error.message, true);
			return;
		}
		sessionFields(typeof sourceId === "string" ? sourceId : state.data?.source?.id);
		$("#session-dialog").showModal();
	}
	function download(blob, filename) {
		const url = URL.createObjectURL(blob), anchor = document.createElement("a");
		anchor.href = url;
		anchor.download = filename;
		document.body.append(anchor);
		anchor.click();
		anchor.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1e4);
	}
	async function exportFile(type) {
		try {
			const date = (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
			if (type === "report") download(new Blob([JSON.stringify(await api.report(), null, 2)], { type: "application/json;charset=utf-8" }), `mawrid-summary-${date}.json`);
			else download(await api.export(type), `mawrid-${type}-${date}.csv`);
			toast("تم تجهيز الملف من السجل المحفوظ.");
		} catch (error) {
			toast(error.message, true);
		}
	}
	function syncMenuAccessibility() {
		const hidden = window.matchMedia?.("(max-width: 900px)")?.matches === true && !$("#sidebar").classList.contains("open");
		$("#sidebar").inert = hidden;
		if (hidden) $("#sidebar").setAttribute("aria-hidden", "true");
		else $("#sidebar").removeAttribute("aria-hidden");
	}
	function closeMenu() {
		const wasOpen = $("#sidebar").classList.contains("open");
		$("#sidebar").classList.remove("open");
		$("#sidebar-backdrop").hidden = true;
		$("#menu-button").setAttribute("aria-expanded", "false");
		syncMenuAccessibility();
		if (wasOpen) $("#menu-button").focus();
	}
	async function startPlant() {
		if (!state.connected) throw new Error("اتصل بالخدمة المحلية قبل تشغيل المنشأة الافتراضية.");
		stopAutoplay();
		await mutate(() => api.createSession("virtual_plant", true));
		state.channel = null;
		state.readings = [];
		state.historyLoaded = false;
		state.guideUi.experienceSession = plantView(state.data).sessionId;
		state.guideUi.experienceRestored = false;
		state.guideUi.journeySession = plantView(state.data).sessionId;
		state.guideUi.journeyIndex = 0;
		state.guideUi.journeyComplete = false;
		if (state.page !== "plant") {
			location.hash = "plant";
			route();
		} else render();
		toast("بدأت المنشأة الافتراضية.");
	}
	async function controlPlant(key, value) {
		if (!plantView(state.data).active || !state.connected) throw new Error("شغّل جلسة المنشأة الافتراضية أولًا.");
		if (!(key === "mode" && Object.hasOwn(PLANT_MODES, value) || key === "fault" && Object.hasOwn(PLANT_FAULTS, value) || key === "speed" && [
			1,
			10,
			30
		].includes(value) || key === "running" && typeof value === "boolean")) throw new Error("أمر المحاكاة غير صالح.");
		await mutate(() => api.plantControl({ [key]: value }));
	}
	function selectEquipment(id) {
		if (!Object.hasOwn(EQUIPMENT, id)) return;
		state.plantUi.equipment = id;
		render();
	}
	async function guideCommand(control) {
		if (!plantView(state.data).active) await startPlant();
		await mutate(() => api.plantControl(control));
	}
	var presenter = new JourneyPresentation();
	var cameraRequest = 0;
	var presentationTextOnly = false;
	var presentationStarting = false;
	var presentationNow = () => globalThis.performance?.now?.() ?? Date.now();
	function presentationContext() {
		const v = plantView(state.data), x = experienceState(state.data, state.guideUi, state.connected);
		return {
			v,
			x,
			ready: state.page === "plant" && state.connected && !document.hidden && !$("#experience-details")?.open && x.id === "journey"
		};
	}
	function syncPresentationView() {
		state.guideUi.presentation = {
			...presenter.view(),
			textOnly: presentationTextOnly
		};
	}
	function pausePresentation(reason = "reading", draw = true) {
		if (presenter.pause(reason, presentationNow())) {
			syncPresentationView();
			if (draw) render();
		}
	}
	function reconcilePresentation() {
		const { v, x } = presentationContext();
		if (presenter.status !== "idle" && presenter.sessionId !== v.sessionId) {
			presenter.stop();
			presentationTextOnly = false;
			cameraRequest++;
		}
		if (presenter.status === "playing") {
			const reason = state.page !== "plant" ? "navigation" : document.hidden ? "hidden" : $("#experience-details")?.open ? "details" : !state.connected ? "connection" : x.id !== "journey" ? "plant" : null;
			if (reason) presenter.pause(reason, presentationNow());
		}
		syncPresentationView();
	}
	function updatePresentationClock() {
		const node = $("#presentation-clock");
		if (!node) return;
		node.textContent = presenter.status === "playing" ? presenter.waitingCamera ? "جارٍ تقريب الجزء…" : `الانتقال بعد ${Math.ceil(presenter.remainingMs / 1e3)} ثانية` : presenter.status === "paused" ? `متبقي ${Math.ceil(presenter.remainingMs / 1e3)} ثانية` : "";
	}
	async function startPresentation() {
		if (state.mutation || presentationStarting) throw new Error("انتظر اكتمال العملية الحالية.");
		const { x } = presentationContext();
		if (![
			"start",
			"paused",
			"journey",
			"normal",
			"done"
		].includes(x.id)) throw new Error("أعد المحاكاة إلى التشغيل الاعتيادي أولًا، ثم ابدأ العرض.");
		presentationStarting = true;
		state.guideUi.experienceError = "";
		try {
			presenter.stop();
			if (x.id === "start") await startPlant();
			else if (x.id === "paused") await controlPlant("running", true);
			const v = plantView(state.data), next = experienceState(state.data, state.guideUi, state.connected);
			if (!v.active || ![
				"journey",
				"normal",
				"done"
			].includes(next.id)) throw new Error("المحاكاة غير جاهزة للعرض. راجع حالتها ثم حاول مجددًا.");
			state.guideUi.journeySession = v.sessionId;
			state.guideUi.journeyIndex = 0;
			state.guideUi.journeyComplete = false;
			state.guideUi.experienceRestored = false;
			presentationTextOnly = false;
			cameraRequest++;
			presenter.start(v.sessionId, presentationNow());
			render();
		} catch (error) {
			state.guideUi.experienceError = error.message;
			render();
			throw error;
		} finally {
			presentationStarting = false;
			mutationUI();
		}
	}
	function resumePresentation() {
		if (state.mutation || !presentationContext().ready) return;
		if (presenter.resume(presentationNow())) {
			cameraRequest++;
			render();
		}
	}
	function stopPresentation() {
		presenter.stop();
		presentationTextOnly = false;
		cameraRequest++;
		render();
	}
	function tickPresentation() {
		reconcilePresentation();
		if (presenter.status !== "playing") {
			syncPresentationView();
			return;
		}
		const now = presentationNow();
		let fallback = false;
		if (presenter.waitingCamera && (presentationTextOnly || now - presenter.waitingSince >= 8e3)) {
			presentationTextOnly = true;
			presenter.settle(journeyProgress(state.guideUi, presenter.sessionId).stage.id, now);
			fallback = true;
		}
		const changed = presenter.tick(now);
		if (changed || fallback) {
			if (changed && presenter.status === "playing") {
				state.guideUi.journeyIndex = presenter.index;
				cameraRequest++;
			}
			syncPresentationView();
			render();
		} else {
			syncPresentationView();
			updatePresentationClock();
		}
	}
	var lastJourneyWindow = null;
	var lastJourneyMessage = "";
	function syncJourneyScene(force = false) {
		if (state.page !== "plant") {
			lastJourneyWindow = null;
			lastJourneyMessage = "";
			return;
		}
		const frame = $("#guide-scene"), v = plantView(state.data);
		if (!frame?.contentWindow) return;
		const x = experienceState(state.data, state.guideUi, state.connected), p = journeyProgress(state.guideUi, v.sessionId);
		const id = !v.active ? null : x.id === "fault" ? v.fault === "sensor_dropout" ? "verify" : v.fault === "clogging" ? "media" : v.fault === "valve_stuck" ? "irrigation" : null : x.id === "done" || p.complete ? "irrigation" : p.stage.id;
		const camera = ["playing", "paused"].includes(presenter.status) && presenter.sessionId === v.sessionId ? "focus" : "overview";
		const signature = JSON.stringify([
			v.sessionId,
			id,
			camera,
			cameraRequest
		]);
		if (force || lastJourneyWindow !== frame.contentWindow || lastJourneyMessage !== signature) {
			frame.contentWindow.postMessage({
				type: "mawrid:journey",
				id,
				camera,
				requestId: cameraRequest
			}, location.origin);
			lastJourneyWindow = frame.contentWindow;
			lastJourneyMessage = signature;
		}
	}
	function moveJourney(direction) {
		if (["playing", "paused"].includes(presenter.status)) {
			presenter.stop();
			presentationTextOnly = false;
			cameraRequest++;
		}
		if (state.mutation || !state.connected) return;
		const v = plantView(state.data), x = experienceState(state.data, state.guideUi, state.connected), p = journeyProgress(state.guideUi, v.sessionId);
		if (direction === "previous" && x.id === "journey") {
			state.guideUi.journeySession = v.sessionId;
			state.guideUi.journeyIndex = Math.max(0, p.index - 1);
		} else if (direction === "replay" && ["done", "normal"].includes(x.id)) {
			state.guideUi.journeySession = v.sessionId;
			state.guideUi.journeyIndex = 0;
			state.guideUi.journeyComplete = false;
			state.guideUi.experienceRestored = false;
		} else return;
		render();
		$("#page-content [data-action=\"experience-next\"]")?.focus({ preventScroll: true });
	}
	window.addEventListener("message", (event) => {
		if (event.origin !== location.origin || event.source !== $("#guide-scene")?.contentWindow) return;
		if (event.data?.type === "mawrid:scene-ready") {
			presentationTextOnly = false;
			syncJourneyScene(true);
		}
		if (event.data?.type === "mawrid:camera-settled" && event.data.requestId === cameraRequest) {
			presenter.settle(event.data.id, presentationNow());
			syncPresentationView();
			updatePresentationClock();
		}
		if (["mawrid:camera-interaction", "mawrid:equipment"].includes(event.data?.type)) pausePresentation("camera");
	});
	async function experienceNext() {
		if (state.mutation) throw new Error("انتظر اكتمال العملية الحالية.");
		if (presenter.status === "playing") pausePresentation("manual", false);
		const before = plantView(state.data);
		const action = experienceState(state.data, state.guideUi, state.connected).action;
		if (!action) return;
		if (["journey-next", "test"].includes(action) && ["playing", "paused"].includes(presenter.status)) {
			presenter.stop();
			presentationTextOnly = false;
			cameraRequest++;
		}
		state.guideUi.experienceError = "";
		try {
			if (action === "journey-next") {
				const p = journeyProgress(state.guideUi, before.sessionId);
				state.guideUi.journeySession = before.sessionId;
				state.guideUi.journeyIndex = Math.min(p.total - 1, p.index + 1);
			} else if (action === "start") await startPlant();
			else if (action === "release") {
				await mutate(() => api.reset());
				return;
			} else {
				const control = action === "test" ? {
					fault: "sensor_dropout",
					mode: "auto",
					speed: 1,
					running: true
				} : action === "restore" ? {
					fault: "none",
					mode: "auto",
					speed: 1,
					running: true
				} : { running: true };
				const v = plantView(await mutate(() => api.plantControl(control)));
				if (action === "test" && v.fault === "sensor_dropout") {
					const p = journeyProgress(state.guideUi, before.sessionId);
					if (p.index === p.total - 1) {
						state.guideUi.journeySession = before.sessionId;
						state.guideUi.journeyComplete = true;
					}
					state.guideUi.experienceSession = v.sessionId;
					state.guideUi.experienceRestored = false;
				}
				if (action === "restore" && before.fault === "sensor_dropout" && before.equipment?.irrigation?.status === "closed" && before.irrigation_flow_lpm === 0 && v.fault === "none" && v.mode === "auto" && v.running) {
					state.guideUi.experienceSession = v.sessionId;
					state.guideUi.experienceRestored = true;
				}
			}
		} catch (error) {
			state.guideUi.experienceError = error.message;
			throw error;
		} finally {
			render();
			if (state.page === "plant") $("#page-content [data-action=\"experience-next\"]")?.focus({ preventScroll: true });
		}
	}
	$("#page-content").addEventListener("click", async (event) => {
		const equipment = event.target.closest("[data-equipment]");
		if (equipment) {
			selectEquipment(equipment.dataset.equipment);
			return;
		}
		const filter = event.target.closest("[data-filter]");
		if (filter) {
			state.alarmFilter = filter.dataset.filter;
			render();
			return;
		}
		const button = event.target.closest("[data-action]");
		if (!button) return;
		const action = button.dataset.action;
		try {
			if (action === "auto-start") {
				await startPresentation();
				$("#page-content [data-action=\"auto-pause\"]")?.focus({ preventScroll: true });
			} else if (action === "auto-pause") {
				pausePresentation();
				$("#page-content [data-action=\"auto-resume\"]")?.focus({ preventScroll: true });
			} else if (action === "auto-resume") {
				resumePresentation();
				$("#page-content [data-action=\"auto-pause\"]")?.focus({ preventScroll: true });
			} else if (action === "auto-stop") {
				stopPresentation();
				$("#page-content [data-action=\"experience-next\"]")?.focus({ preventScroll: true });
			} else if (action === "experience-next") await experienceNext();
			else if (action === "journey-previous") moveJourney("previous");
			else if (action === "journey-replay") moveJourney("replay");
			else if (action === "experience-details") {
				pausePresentation("details", false);
				$("#experience-details")?.showModal();
				render();
			} else if (action === "experience-close") {
				$("#experience-details")?.close();
				render();
			} else if (action === "guide-tour" || action === "guide-tour-next") {
				state.guideUi.tourStep = action === "guide-tour-next" ? Math.min(2, state.guideUi.tourStep + 1) : Math.max(0, Math.min(2, Number(button.dataset.step) || 0));
				updateTour($("#page-content"), state.guideUi);
				mutationUI();
			} else if (action === "guide-component") {
				state.guideUi.component = button.dataset.component;
				updateComponent($("#page-content"), state.guideUi);
			} else if (action === "guide-normal") await guideCommand({
				fault: "none",
				mode: "auto",
				running: true
			});
			else if (action === "guide-fault") await guideCommand({
				fault: "sensor_dropout",
				mode: "auto",
				running: true
			});
			else if (action === "guide-clear") await guideCommand({
				fault: "none",
				mode: "auto",
				running: true
			});
			else if (action === "new-session") await openSession();
			else if (action === "plant-zoom") {
				state.plantUi.zoom = !state.plantUi.zoom;
				render();
			} else if (action === "plant-start") await startPlant();
			else if (action === "plant-speed") await controlPlant("speed", Number(button.dataset.speed));
			else if (action === "plant-running") {
				await controlPlant("running", !plantView(state.data).running);
				if (state.page === "plant") $("#page-content [data-action=\"experience-next\"]")?.focus({ preventScroll: true });
			} else if (action === "telemetry-session") await openSession("telemetry");
			else if (action === "copy-telemetry-session") await copyTelemetrySession();
			else if (action === "retry") await refresh({ all: true });
			else if (action === "play") await play();
			else if (action === "pause") await pause();
			else if (action === "step") {
				if (!canReplay()) return;
				await mutate(() => api.step(1));
			} else if (action === "ack") {
				await mutate(() => api.acknowledge(button.dataset.id));
				await loadAlarms();
				toast("سُجل اطلاعك على التنبيه.");
			} else if (action === "refresh-alarms") await loadAlarms();
			else if (action === "refresh-history") await loadHistory();
			else if (action.startsWith("export-")) await exportFile(action.slice(7));
			else if (action === "reload-settings") {
				const result = await api.settings();
				state.data.settings = result.settings;
				render(true);
			} else if (action === "hold") {
				await pause();
				await mutate(() => api.stop());
				toast("ثُبّت الاحتجاز البرمجي. لا أوامر لعتاد فعلي.");
			} else if (action === "reset") {
				await mutate(() => api.reset());
				toast("أزيل الطلب اليدوي. يبقى الصمام البرمجي مغلقًا.");
			} else if (action === "telemetry-help") location.hash = "settings";
		} catch (error) {
			toast(error.message, true);
		}
	});
	$("#page-content").addEventListener("input", (event) => {
		if (event.target.id !== "guide-component-search") return;
		const query = event.target.value.trim();
		let count = 0;
		$("#page-content").querySelectorAll("[data-component]").forEach((b) => {
			const show = b.textContent.includes(query);
			b.hidden = !show;
			if (show) count++;
		});
		$("#guide-component-count").textContent = count ? `النتائج: ${count}` : "لا يوجد جزء بهذا الاسم. جرّب كلمة أخرى.";
	});
	$("#page-content").addEventListener("change", async (event) => {
		const target = event.target;
		if (target.id === "guide-speed") {
			try {
				await controlPlant("speed", Number(target.value));
			} catch (error) {
				toast(error.message, true);
				render();
			}
			return;
		}
		if (target.id === "plant-mode" || target.id === "plant-fault") {
			try {
				await controlPlant(target.id === "plant-mode" ? "mode" : "fault", target.value);
			} catch (error) {
				toast(error.message, true);
				render();
			}
			return;
		}
		if (target.id === "chart-channel") {
			state.channel = target.value;
			render();
		}
		if (target.id === "batch-size") state.batch = Math.max(1, Math.min(25, Number(target.value) || 1));
		if (target.id === "history-scope") {
			state.historyScope = target.value;
			await loadHistory();
		}
		if (target.id === "history-limit") {
			state.historyLimit = Number(target.value);
			await loadHistory();
		}
	});
	$("#page-content").addEventListener("keydown", (event) => {
		const equipment = event.target.closest("[data-equipment]");
		if (equipment && ["Enter", " "].includes(event.key)) {
			event.preventDefault();
			selectEquipment(equipment.dataset.equipment);
		}
	});
	$("#page-content").addEventListener("submit", async (event) => {
		if (event.target.id !== "settings-form") return;
		event.preventDefault();
		const form = event.target, values = new FormData(form), settings = { site_name: String(values.get("site_name")).trim() };
		for (const [key] of settingsFields) settings[key] = Number(values.get(key));
		const errorNode = $("#settings-error");
		errorNode.hidden = true;
		if (settings.ph_min >= settings.ph_max || settings.chlorine_min >= settings.chlorine_max) {
			errorNode.textContent = "يجب أن يكون الحد الأدنى أقل من الحد الأعلى.";
			errorNode.hidden = false;
			return;
		}
		try {
			await mutate(() => api.saveSettings(settings));
			state.settingsRendered = false;
			render(true);
			toast("حُفظت الإعدادات التجريبية. نموذج ML لم يتغير.");
		} catch (error) {
			const current = $("#settings-error");
			if (current) {
				current.textContent = error.message;
				current.hidden = false;
			}
		}
	});
	$("#session-form").addEventListener("change", (event) => {
		if (event.target.id === "session-source") sessionFields(event.target.value);
		else mutationUI();
	});
	$("#session-form").addEventListener("submit", async (event) => {
		event.preventDefault();
		if (!$("#research-ack")?.checked) return;
		stopAutoplay();
		$("#session-error").hidden = true;
		try {
			if (state.mutation) await state.mutation;
			await mutate(() => api.createSession($("#session-source").value, $("#research-ack").checked));
			state.readings = [];
			state.historyLoaded = false;
			state.alarmsLoaded = false;
			$("#session-dialog").close();
			state.channel = null;
			location.hash = state.data?.source?.kind === "digital_twin" ? "plant" : "overview";
			route();
			toast(state.data?.source?.kind === "digital_twin" ? "بدأت جلسة المنشأة الافتراضية." : "الجلسة جاهزة.");
		} catch (error) {
			$("#session-error").textContent = error.message;
			$("#session-error").hidden = false;
		}
	});
	document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $("#session-dialog").close()));
	$("#new-session-button").addEventListener("click", openSession);
	$("#refresh-button").addEventListener("click", () => refresh({ all: true }));
	$("#retry-button").addEventListener("click", () => refresh({ all: true }));
	$("#menu-button").addEventListener("click", () => {
		const open = !$("#sidebar").classList.contains("open");
		$("#sidebar").classList.toggle("open", open);
		$("#sidebar-backdrop").hidden = !open;
		$("#menu-button").setAttribute("aria-expanded", String(open));
		syncMenuAccessibility();
		if (open) $("#main-nav a")?.focus();
	});
	$("#sidebar-backdrop").addEventListener("click", closeMenu);
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape") {
			const wasOpen = $("#sidebar").classList.contains("open");
			closeMenu();
			if (wasOpen) $("#menu-button").focus();
		}
	});
	document.addEventListener("visibilitychange", () => {
		if (document.hidden) pausePresentation("hidden");
		if (document.hidden && state.autoplay) pause();
		else if (!document.hidden) refresh({ all: true });
	});
	window.addEventListener("hashchange", route);
	window.addEventListener("beforeunload", () => {
		stopAutoplay();
		presenter.stop();
	});
	window.matchMedia?.("(max-width: 900px)")?.addEventListener?.("change", syncMenuAccessibility);
	$("#local-date").textContent = (/* @__PURE__ */ new Date()).toLocaleDateString("ar-SA", {
		weekday: "long",
		day: "numeric",
		month: "long",
		calendar: "gregory"
	});
	$("#page-content").innerHTML = "<div class=\"loading-block\"><div class=\"loading-line\"></div>جارٍ الاتصال بمورد…</div>";
	route();
	refresh();
	setInterval(() => {
		if (!document.hidden && !state.autoplay) refresh();
	}, 2e3);
	setInterval(tickPresentation, 1e3);
	//#endregion
})();
