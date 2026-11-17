(() => {
  const THEME_KEY = "ccw-theme";
  const LANG_KEY = "ccw-lang";

  const copy = {
    en: {
      "meta.description":
        "comp-chem-world — scalable Harbor-based computational chemistry agent benchmark with 245 research tasks across 38 paper-derived benches, plus a repo pipeline to expand coverage. Offline inputs from AI4EC.",
      "meta.title": "comp-chem-world · Computational Chemistry Agent Benchmark",
      "nav.abstract": "Abstract",
      "nav.pipeline": "Pipeline",
      "nav.coverage": "Coverage",
      "nav.start": "Start",
      "theme.label": "Theme",
      "theme.toLight": "Switch to light theme",
      "theme.toDark": "Switch to dark theme",
      "lang.label": "Language",
      "lang.toZh": "Switch to Chinese",
      "lang.toEn": "Switch to English",
      "hero.kicker": "AI for Science · computational chemistry",
      "hero.tagline":
        "A Harbor-based, scalable benchmark for computational chemistry agents—paper-grounded tasks, shared Docker images, offline evaluation, and a repo pipeline built to grow the suite.",
      "hero.status": "Rapid iteration and evaluation in progress.",
      "btn.repo": "Repository",
      "btn.start": "Quick start",
      "stat.tasks": "Research tasks",
      "stat.benches": "Paper benches",
      "stat.local": "Local",
      "stat.hpc": "HPC",
      "section.abstract": "Abstract",
      "abstract.p1":
        "<strong>comp-chem-world</strong> evaluates agents on computational chemistry workflows—geometry and thermochemistry audits, MD diagnostics, ML potentials, spectroscopy, electrocatalysis, and related paper-derived problems—inside Harbor sandboxes with numeric verifiers.",
      "abstract.p2":
        'The scored benchmark is <strong>245 research tasks</strong> (001–245) indexed to <strong>38 paper-linked benches</strong>: <strong>195 local</strong> + <strong>50 HPC</strong>. Local runs use shared base images; HPC tasks need a separate connectivity image. Place the single offline archive from <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a> at <code>shared/inputs.tar.zst</code>, then <code>uv run init</code>.',
      "abstract.p3":
        'The same layout is built to <strong>scale</strong>: add Harbor tasks under <code>tasks/</code>, restore the shared wheelhouse and asset-store with init, and run concurrent jobs via the <code>local-a</code>/<code>local-b</code> and <code>hpc</code> configs.',
      "section.pipeline": "Pipeline",
      "pipe.1.title": "Offline inputs",
      "pipe.1.body":
        'Obtain <code>inputs.tar.zst</code> from <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a>; place at <code>shared/inputs.tar.zst</code> (do not unpack by hand).',
      "pipe.2.title": "Initialize",
      "pipe.2.body":
        "<code>uv run init</code> restores wheels/assets, writes <code>.env</code>, and builds base images.",
      "pipe.3.title": "Model",
      "pipe.3.body":
        "Set <code>ANTHROPIC_API_KEY</code> / <code>ANTHROPIC_BASE_URL</code>; override model in <code>configs/agent.yaml</code> or CLI.",
      "pipe.4.title": "Harbor",
      "pipe.4.body":
        "<code>harbor run -c configs/local.yaml -c configs/agent.yaml</code>; use <code>local-a</code>/<code>local-b</code> or <code>hpc.yaml</code> as needed.",
      "section.coverage": "Coverage",
      "theme.1.title": "Reactions & kinetics",
      "theme.1.body":
        "Activation energies, aromatic radical rearrangements, organic emitters, reaction-space ML.",
      "theme.2.title": "Interfaces & electrocatalysis",
      "theme.2.body": "CO<sub>2</sub> reduction, double-layer charging, hydration forces.",
      "theme.3.title": "ML potentials & sampling",
      "theme.3.body":
        "Deep eutectic solvents, DeepVES, NewtonNet Hessians, metals MLPs, zeolite NNs.",
      "theme.4.title": "Materials & transport",
      "theme.4.body":
        "Carrier scattering, Li titanate, layered lattices, phonon superconductivity, BaTiO<sub>3</sub>.",
      "theme.5.title": "Soft matter & biomolecules",
      "theme.5.body":
        "Condensates, host–guest water, Hsp60, protein–drug refinement, constant-pH MD.",
      "theme.6.title": "Spectra, solvents & workflows",
      "theme.6.body":
        "IR elucidation, NEP IR/Raman, AutoSolvateWeb, ChemGraph, Ai2-Kit pipelines.",
      "section.start": "Quick start",
      "terminal.comment":
        "# uv · clone · place shared/inputs.tar.zst (from AI4EC)\nuv run init\n# .env → ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL\nuv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y",
      "btn.readme": "README",
      "btn.catalog": "Paper ↔ task catalog",
      "footnote":
        "Counts above exclude <code>000-hello</code>, a smoke-test demo task.",
      "footer.text":
        '<span class="brand-inline">comp-chem-world</span> · computational chemistry agent environments · offline inputs from <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a>',
      "footer.contact":
        'Collaboration: <a href="mailto:sheng.bi@xmu.edu.cn">sheng.bi@xmu.edu.cn</a> · <a href="mailto:gongyulei@stu.xmu.edu.cn">gongyulei@stu.xmu.edu.cn</a>',
    },
    zh: {
      "meta.description":
        "comp-chem-world — 可扩展的 Harbor 计算化学智能体评测基准，涵盖 38 个论文衍生 bench、245 项研究任务，并自带扩充覆盖面的仓库流水线；离线输入由 AI4EC 分发。",
      "meta.title": "comp-chem-world · 计算化学智能体评测基准",
      "nav.abstract": "摘要",
      "nav.pipeline": "流程",
      "nav.coverage": "覆盖面",
      "nav.start": "开始",
      "theme.label": "明暗",
      "theme.toLight": "切换到浅色主题",
      "theme.toDark": "切换到深色主题",
      "lang.label": "语言",
      "lang.toZh": "切换到中文",
      "lang.toEn": "切换到英文",
      "hero.kicker": "AI for Science · 计算化学",
      "hero.tagline":
        "面向计算化学智能体的可扩展 Harbor 评测基准——论文落地任务、共享 Docker 镜像、离线评测，以及可快速扩充任务集的工程流水线。",
      "hero.status": "正在快速迭代和测评中。",
      "btn.repo": "代码仓库",
      "btn.start": "快速开始",
      "stat.tasks": "研究任务",
      "stat.benches": "论文基准",
      "stat.local": "本地",
      "stat.hpc": "HPC",
      "section.abstract": "摘要",
      "abstract.p1":
        "<strong>comp-chem-world</strong> 在 Harbor 沙箱中评测智能体完成计算化学工作流的能力——几何与热化学核查、分子动力学诊断、机器学习势、光谱、电催化及相关论文衍生问题——并以数值 verifier 打分。",
      "abstract.p2":
        '计分基准共 <strong>245 项研究任务</strong>（001–245），对应 <strong>38 个论文关联 bench</strong>：<strong>195 本地</strong> + <strong>50 HPC</strong>。本地任务使用共享基础镜像；HPC 任务需另行构建连通镜像。将 <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a> 提供的单一离线归档置于 <code>shared/inputs.tar.zst</code>，然后执行 <code>uv run init</code>。',
      "abstract.p3":
        '同一套布局为<strong>扩展</strong>而设计：在 <code>tasks/</code> 下新增 Harbor 任务、由 init 恢复共享 wheelhouse 与 asset-store，并通过 <code>local-a</code>/<code>local-b</code> 与 <code>hpc</code> 配置并发运行。',
      "section.pipeline": "流程",
      "pipe.1.title": "离线输入",
      "pipe.1.body":
        '从 <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a> 获取 <code>inputs.tar.zst</code>，放到 <code>shared/inputs.tar.zst</code>（勿手动解压）。',
      "pipe.2.title": "初始化",
      "pipe.2.body":
        "<code>uv run init</code> 恢复 wheels/资产、写入 <code>.env</code>，并构建基础镜像。",
      "pipe.3.title": "模型",
      "pipe.3.body":
        "设置 <code>ANTHROPIC_API_KEY</code> / <code>ANTHROPIC_BASE_URL</code>；可在 <code>configs/agent.yaml</code> 或命令行覆盖模型。",
      "pipe.4.title": "Harbor",
      "pipe.4.body":
        "运行 <code>harbor run -c configs/local.yaml -c configs/agent.yaml</code>；可按需使用 <code>local-a</code>/<code>local-b</code> 或 <code>hpc.yaml</code>。",
      "section.coverage": "覆盖面",
      "theme.1.title": "反应与动力学",
      "theme.1.body": "活化能、芳香自由基重排、有机发光体、反应空间机器学习。",
      "theme.2.title": "界面与电催化",
      "theme.2.body": "CO<sub>2</sub> 还原、双电层充放电、水合作用力。",
      "theme.3.title": "机器学习势与采样",
      "theme.3.body": "深共晶溶剂、DeepVES、NewtonNet Hessian、金属 MLP、沸石神经网络。",
      "theme.4.title": "材料与输运",
      "theme.4.body": "载流子散射、钛酸锂、层状晶格、声子超导、BaTiO<sub>3</sub>。",
      "theme.5.title": "软物质与生物分子",
      "theme.5.body": "凝聚体、主客体水合、Hsp60、蛋白–药物精修、恒 pH 分子动力学。",
      "theme.6.title": "光谱、溶剂与工作流",
      "theme.6.body": "红外解析、NEP 红外/拉曼、AutoSolvateWeb、ChemGraph、Ai2-Kit 流程。",
      "section.start": "快速开始",
      "terminal.comment":
        "# uv · clone · 放置 shared/inputs.tar.zst（来自 AI4EC）\nuv run init\n# .env → ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL\nuv run harbor run -c configs/local.yaml -c configs/agent.yaml --env-file .env -y",
      "btn.readme": "README",
      "btn.catalog": "论文 ↔ 任务目录",
      "footnote":
        "以上数量不含冒烟演示任务 <code>000-hello</code>。",
      "footer.text":
        '<span class="brand-inline">comp-chem-world</span> · 计算化学智能体环境 · 离线输入由 <a href="https://ai4ec.ac.cn" target="_blank" rel="noopener">AI4EC</a> 提供',
      "footer.contact":
        '合作请联系 <a href="mailto:sheng.bi@xmu.edu.cn">sheng.bi@xmu.edu.cn</a> · <a href="mailto:gongyulei@stu.xmu.edu.cn">gongyulei@stu.xmu.edu.cn</a>',
    },
  };

  const resolveTheme = () => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  };

  const resolveLang = () => {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "en" || saved === "zh") return saved;
    const nav = (navigator.language || "").toLowerCase();
    return nav.startsWith("zh") ? "zh" : "en";
  };

  const applyTheme = (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    const next = theme === "dark" ? "light" : "dark";
    const dict = copy[document.documentElement.lang.startsWith("zh") ? "zh" : "en"];
    btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    btn.setAttribute("aria-label", next === "light" ? dict["theme.toLight"] : dict["theme.toDark"]);
    btn.title = dict["theme.label"];
  };

  const applyLang = (lang) => {
    const dict = copy[lang] || copy.en;
    document.documentElement.lang = lang === "zh" ? "zh-Hans" : "en";
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute("content", dict["meta.description"]);
    if (dict["meta.title"]) document.title = dict["meta.title"];

    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      const value = dict[key];
      if (value == null) return;
      if (el.hasAttribute("data-i18n-html")) {
        el.innerHTML = value;
      } else {
        el.textContent = value;
      }
    });

    const langBtn = document.getElementById("lang-toggle");
    if (langBtn) {
      langBtn.setAttribute("aria-label", lang === "zh" ? dict["lang.toEn"] : dict["lang.toZh"]);
      langBtn.title = dict["lang.label"];
    }

    applyTheme(document.documentElement.getAttribute("data-theme") || resolveTheme());
  };

  const themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || resolveTheme();
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  }

  const langBtn = document.getElementById("lang-toggle");
  if (langBtn) {
    langBtn.addEventListener("click", () => {
      const current = document.documentElement.lang.startsWith("zh") ? "zh" : "en";
      const next = current === "zh" ? "en" : "zh";
      localStorage.setItem(LANG_KEY, next);
      applyLang(next);
    });
  }

  applyTheme(resolveTheme());
  applyLang(resolveLang());

  /* header escapes the slab frame once the page starts scrolling */
  const siteHeader = document.querySelector(".site-header");
  if (siteHeader) {
    const syncHeader = () => siteHeader.classList.toggle("escaped", window.scrollY > 1);
    window.addEventListener("scroll", syncHeader, { passive: true });
    syncHeader();
  }

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ————— The molecular stage: procedurally built SVG behind the glass ————— */

  const NS = "http://www.w3.org/2000/svg";

  const mk = (tag, attrs = {}, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  };

  const atom = (g, x, y, r, kind, extra = {}) =>
    mk("circle", { cx: x.toFixed(1), cy: y.toFixed(1), r: r.toFixed(1), class: `atom atom-${kind}`, ...extra }, g);

  const bond = (g, x1, y1, x2, y2, w = 2.4, cls = "bond") =>
    mk("line", {
      x1: x1.toFixed(1), y1: y1.toFixed(1), x2: x2.toFixed(1), y2: y2.toFixed(1),
      class: cls, "stroke-width": w, "stroke-linecap": "round",
    }, g);

  // axonometric projection: z points up
  const iso = (x, y, z) => [(x - y) * 0.8660254, (x + y) * 0.5 - z];
  const depthOf = (v) => v[0] + v[1] + v[2] * 0.001;

  const ATOM_KINDS = ["c", "h", "o", "n", "ti", "ba", "m", "x", "au"];

  function buildDefs(svg) {
    const defs = mk("defs", {}, svg);
    // sphere gradients: offset highlight -> base -> shaded rim (theme-aware via CSS vars)
    for (const k of ATOM_KINDS) {
      const grad = mk("radialGradient", { id: `g-${k}`, cx: "35%", cy: "30%", r: "85%" }, defs);
      mk("stop", { offset: "0%", style: `stop-color: color-mix(in srgb, var(--atom-${k}) 40%, #fff)` }, grad);
      mk("stop", { offset: "42%", style: `stop-color: var(--atom-${k})` }, grad);
      mk("stop", { offset: "100%", style: `stop-color: color-mix(in srgb, var(--atom-${k}) 68%, #000)` }, grad);
    }
    // orbital phase lobes
    for (const [id, v] of [["lobeA", "--lobe-a"], ["lobeB", "--lobe-b"]]) {
      const grad = mk("radialGradient", { id }, defs);
      mk("stop", { offset: "0%", style: `stop-color: color-mix(in srgb, var(${v}) 72%, #fff); stop-opacity: 0.8` }, grad);
      mk("stop", { offset: "70%", style: `stop-color: var(${v}); stop-opacity: 0.45` }, grad);
      mk("stop", { offset: "100%", style: `stop-color: var(${v}); stop-opacity: 0` }, grad);
    }
    // soft electron-density glow
    const glow = mk("radialGradient", { id: "glowS" }, defs);
    mk("stop", { offset: "0%", style: "stop-color: color-mix(in srgb, var(--glow) 70%, #fff); stop-opacity: 0.5" }, glow);
    mk("stop", { offset: "55%", style: "stop-color: var(--glow); stop-opacity: 0.2" }, glow);
    mk("stop", { offset: "100%", style: "stop-color: var(--glow); stop-opacity: 0" }, glow);
    // radial fade mask for framework fragments
    const fade = mk("radialGradient", { id: "fadeG" }, defs);
    mk("stop", { offset: "52%", style: "stop-color: #fff; stop-opacity: 1" }, fade);
    mk("stop", { offset: "100%", style: "stop-color: #fff; stop-opacity: 0" }, fade);
    const mask = mk("mask", { id: "fadeM", maskContentUnits: "objectBoundingBox" }, defs);
    mk("rect", { x: 0, y: 0, width: 1, height: 1, fill: "url(#fadeG)" }, mask);
  }

  const group = (parent, cx, cy, rot, anim, masked) => {
    const outer = mk("g", { transform: `translate(${cx} ${cy}) rotate(${rot})` }, parent);
    return mk("g", { class: anim || "", ...(masked ? { mask: "url(#fadeM)" } : {}) }, outer);
  };

  const glowSpot = (parent, x, y, r, opacity = 0.55) =>
    mk("circle", { cx: x, cy: y, r, fill: "url(#glowS)", opacity }, parent);

  const loneAtoms = (parent, list) =>
    list.forEach(([x, y, r, k, o]) => atom(parent, x, y, r, k, { opacity: o }));

  /* ball-and-stick pieces */

  function benzene(parent, cx, cy, R, rot) {
    const outer = mk("g", { transform: `translate(${cx} ${cy}) rotate(${rot})` }, parent);
    // observation reticle stays fixed on the specimen while the ring drifts
    mk("circle", { cx: 0, cy: 0, r: R * 2.2, class: "reticle-ring" }, outer);
    for (const [x1, y1, x2, y2] of [
      [R * 2.2 + 7, 0, R * 2.2 + 18, 0], [-R * 2.2 - 7, 0, -R * 2.2 - 18, 0],
      [0, R * 2.2 + 7, 0, R * 2.2 + 18], [0, -R * 2.2 - 7, 0, -R * 2.2 - 18],
    ]) mk("line", { x1, y1, x2, y2, class: "reticle-tick" }, outer);
    const g = mk("g", { class: "bob" }, outer);
    const pts = [];
    for (let k = 0; k < 6; k++) {
      const a = Math.PI / 6 + (Math.PI / 3) * k;
      pts.push([R * Math.cos(a), R * Math.sin(a)]);
    }
    for (let k = 0; k < 6; k++) bond(g, ...pts[k], ...pts[(k + 1) % 6], R * 0.05, "bond-strong");
    mk("circle", { cx: 0, cy: 0, r: R * 0.52, class: "ring-inner", style: `stroke-width:${(R * 0.028).toFixed(1)}` }, g);
    pts.forEach(([x, y]) => atom(g, x, y, R * 0.3, "c"));
    for (let k = 0; k < 6; k += 2) {
      const [x, y] = pts[k];
      const ux = x / R, uy = y / R;
      bond(g, x, y, x + ux * R * 0.62, y + uy * R * 0.62, R * 0.022, "bond-soft");
      atom(g, x + ux * R * 0.78, y + uy * R * 0.78, R * 0.16, "h");
    }
  }

  function biphenyl(parent, cx, cy, R, rot) {
    const g = group(parent, cx, cy, rot, "bob-alt");
    bond(g, -0.5 * R, 0, 0.6 * R, 0, R * 0.045, "bond"); // inter-ring sp2 link, drawn under the atoms
    const ring = (rc, scale) => {
      const pts = [];
      for (let k = 0; k < 6; k++) {
        const a = (Math.PI / 3) * k; // flat-side out: a carbon points at the partner ring
        pts.push([rc + scale * R * Math.cos(a), scale * R * Math.sin(a)]);
      }
      for (let k = 0; k < 6; k++) bond(g, ...pts[k], ...pts[(k + 1) % 6], scale * R * 0.05, "bond-strong");
      mk("circle", { cx: rc, cy: 0, r: scale * R * 0.52, class: "ring-inner", style: `stroke-width:${(scale * R * 0.028).toFixed(1)}` }, g);
      pts.forEach(([x, y]) => atom(g, x, y, scale * R * 0.3, "c"));
    };
    ring(-R * 1.5, 1);
    ring(R * 1.5, 0.9); // smaller far ring suggests the dihedral twist
  }

  function waterCluster(parent, cx, cy, s, rot) {
    const g = group(parent, cx, cy, rot, "bob");
    const oxy = [[0, 0, 200], [s * 0.95, -s * 0.32, 40], [s * 0.3, s * 0.72, 290]];
    for (let i = 0; i < oxy.length; i++)
      for (let j = i + 1; j < oxy.length; j++)
        bond(g, oxy[i][0], oxy[i][1], oxy[j][0], oxy[j][1], s * 0.01, "bond-dash");
    for (const [ox, oy, deg] of oxy) {
      for (const off of [-52, 52]) {
        const a = ((deg + off) * Math.PI) / 180;
        const hx = ox + Math.cos(a) * s * 0.34, hy = oy + Math.sin(a) * s * 0.34;
        bond(g, ox, oy, hx, hy, s * 0.016, "bond");
        atom(g, hx, hy, s * 0.115, "h");
      }
    }
    for (const [ox, oy] of oxy) atom(g, ox, oy, s * 0.22, "o");
  }

  /* crystal cells (BaTiO3 perovskite + FCC metal) */

  const cubeEdges = (corners) => {
    const edges = [];
    for (let i = 0; i < corners.length; i++)
      for (let j = i + 1; j < corners.length; j++) {
        const diff = corners[i].filter((v, k) => Math.abs(v - corners[j][k]) > 0.01).length;
        if (diff === 1) edges.push([corners[i], corners[j]]);
      }
    return edges;
  };

  const CORNERS = [];
  for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) CORNERS.push([x, y, z]);
  const FACES = [[0.5, 0, 0], [-0.5, 0, 0], [0, 0.5, 0], [0, -0.5, 0], [0, 0, 0.5], [0, 0, -0.5]];

  function perovskite(parent, cx, cy, s) {
    const g = group(parent, cx, cy, 0, "bob");
    const P = (v) => iso(v[0] * s, v[1] * s, v[2] * s);
    for (const [a, b] of cubeEdges(CORNERS)) bond(g, ...P(a), ...P(b), s * 0.007, "bond-frame");
    const center = P([0, 0, 0]);
    for (const f of FACES) bond(g, ...center, ...P(f), s * 0.011, "bond-strong");
    const items = [
      ...CORNERS.map((c) => ({ p: P(c), r: 0.14 * s, k: "ba", d: depthOf(c) })),
      ...FACES.map((f) => ({ p: P(f), r: 0.115 * s, k: "o", d: depthOf(f) })),
      { p: center, r: 0.12 * s, k: "ti", d: 0.001 },
    ].sort((a, b) => a.d - b.d);
    for (const it of items) atom(g, it.p[0], it.p[1], it.r, it.k);
  }

  function fccCell(parent, cx, cy, s) {
    const g = group(parent, cx, cy, 0, "bob-alt");
    const P = (v) => iso(v[0] * s, v[1] * s, v[2] * s);
    for (const [a, b] of cubeEdges(CORNERS)) bond(g, ...P(a), ...P(b), s * 0.007, "bond-frame");
    const items = [
      ...CORNERS.map((c) => ({ p: P(c), r: 0.13 * s, d: depthOf(c) })),
      ...FACES.map((f) => ({ p: P(f), r: 0.155 * s, d: depthOf(f) })),
    ].sort((a, b) => a.d - b.d);
    for (const it of items) atom(g, it.p[0], it.p[1], it.r, "m");
  }

  /* coordination polyhedra */

  function octahedron(parent, cx, cy, s, rot) {
    const g = group(parent, cx, cy, rot, "spin-slow");
    const V = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1.15], [0, 0, -1.15]];
    const P = (v) => iso(v[0] * s, v[1] * s, v[2] * s);
    const antipodal = new Set(["0-1", "1-0", "2-3", "3-2", "4-5", "5-4"]);
    for (const f of [[4, 0, 2], [4, 2, 1], [4, 1, 3], [4, 3, 0], [5, 0, 2], [5, 3, 0]]) {
      const pts = f.map((i) => P(V[i]).join(",")).join(" ");
      mk("polygon", { points: pts, class: "face" }, g);
    }
    for (let i = 0; i < V.length; i++)
      for (let j = i + 1; j < V.length; j++)
        if (!antipodal.has(`${i}-${j}`)) bond(g, ...P(V[i]), ...P(V[j]), s * 0.011, "bond-soft");
    const center = P([0, 0, 0]);
    for (const v of V) bond(g, ...center, ...P(v), s * 0.017, "bond-strong");
    const items = V.map((v) => ({ p: P(v), d: depthOf(v) })).sort((a, b) => a.d - b.d);
    for (const it of items) atom(g, it.p[0], it.p[1], 0.16 * s, "x");
    atom(g, center[0], center[1], 0.17 * s, "m");
  }

  function tetrahedron(parent, cx, cy, s, rot) {
    const g = group(parent, cx, cy, rot, "spin-rev");
    const V = [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]].map(
      (v) => [v[0] * 0.8, v[1] * 0.8, v[2] * 0.8]
    );
    const P = (v) => iso(v[0] * s, v[1] * s, v[2] * s);
    for (const f of [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]) {
      const pts = f.map((i) => P(V[i]).join(",")).join(" ");
      mk("polygon", { points: pts, class: "face" }, g);
    }
    for (let i = 0; i < V.length; i++)
      for (let j = i + 1; j < V.length; j++) bond(g, ...P(V[i]), ...P(V[j]), s * 0.011, "bond-soft");
    const center = P([0, 0, 0]);
    for (const v of V) bond(g, ...center, ...P(v), s * 0.017, "bond-strong");
    const items = V.map((v) => ({ p: P(v), d: depthOf(v) })).sort((a, b) => a.d - b.d);
    for (const it of items) atom(g, it.p[0], it.p[1], 0.17 * s, "x");
    atom(g, center[0], center[1], 0.16 * s, "m");
  }

  /* periodic frameworks: graphene patch + MOF grid + helix */

  function graphene(parent, cx, cy, R, rot, cols, rows) {
    const g = group(parent, cx, cy, rot, "", true);
    const hexW = 1.5 * R, hexH = Math.sqrt(3) * R;
    const seen = new Set();
    const keyed = new Set();
    const key = (x, y) => `${Math.round(x * 2)},${Math.round(y * 2)}`;
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        const ox = i * hexW - (cols * hexW) / 2;
        const oy = j * hexH + (i % 2 ? hexH / 2 : 0) - (rows * hexH) / 2;
        const verts = [];
        for (let k = 0; k < 6; k++) {
          const a = (Math.PI / 3) * k;
          verts.push([ox + R * Math.cos(a), oy + R * Math.sin(a)]);
        }
        for (let k = 0; k < 6; k++) {
          const [x1, y1] = verts[k], [x2, y2] = verts[(k + 1) % 6];
          const ek = [key(x1, y1), key(x2, y2)].sort().join("|");
          if (!seen.has(ek)) {
            seen.add(ek);
            bond(g, x1, y1, x2, y2, R * 0.05, "bond-soft");
          }
          const kk = key(x1, y1);
          if (!keyed.has(kk)) {
            keyed.add(kk);
            atom(g, x1, y1, R * 0.26, "c");
          }
        }
      }
    }
  }

  function mofGrid(parent, cx, cy, s, rot, cols, rows) {
    const g = group(parent, cx, cy, rot, "", true);
    const w = (cols - 1) * s, h = (rows - 1) * s;
    const X = (i) => -w / 2 + i * s, Y = (j) => -h / 2 + j * s;
    for (let i = 0; i < cols; i++)
      for (let j = 0; j < rows; j++) {
        if (i + 1 < cols) {
          bond(g, X(i), Y(j), X(i + 1), Y(j), s * 0.02, "bond-soft");
          atom(g, (X(i) + X(i + 1)) / 2, Y(j), s * 0.032, "c");
        }
        if (j + 1 < rows) {
          bond(g, X(i), Y(j), X(i), Y(j + 1), s * 0.02, "bond-soft");
          atom(g, X(i), (Y(j) + Y(j + 1)) / 2, s * 0.032, "c");
        }
      }
    for (let i = 0; i < cols; i++)
      for (let j = 0; j < rows; j++) {
        const x = X(i), y = Y(j);
        for (const [dx, dy] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) atom(g, x + dx * s * 0.11, y + dy * s * 0.11, s * 0.042, "o");
        atom(g, x, y, s * 0.075, "m");
      }
  }

  function helix(parent, cx, cy, len, rot) {
    const g = group(parent, cx, cy, rot, "bob");
    const n = 22, turns = 2.2, amp = 34;
    let prevA = null, prevB = null;
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      const x = -len / 2 + t * len;
      const ph = t * Math.PI * 2 * turns;
      const ya = amp * Math.sin(ph), yb = amp * Math.sin(ph + Math.PI);
      const depth = Math.cos(ph);
      if (prevA) {
        bond(g, prevA[0], prevA[1], x, ya, 2.2, "bond-soft");
        bond(g, prevB[0], prevB[1], x, yb, 2.2, "bond-soft");
      }
      if (i % 4 === 0) bond(g, x, ya, x, yb, 1.5, "bond-dash");
      atom(g, x, ya, 7 * (1 + 0.22 * depth), i % 2 ? "o" : "n", { opacity: (0.65 + 0.35 * (0.5 + 0.5 * depth)).toFixed(2) });
      atom(g, x, yb, 7 * (1 - 0.22 * depth), i % 2 ? "n" : "o", { opacity: (0.65 + 0.35 * (0.5 - 0.5 * depth)).toFixed(2) });
      prevA = [x, ya];
      prevB = [x, yb];
    }
  }

  /* orbitals */

  function pOrbital(parent, cx, cy, s, rot, anim) {
    const g = group(parent, cx, cy, rot, anim);
    mk("ellipse", { cx: -s * 0.5, cy: 0, rx: s * 0.58, ry: s * 0.3, fill: "url(#lobeA)", opacity: 0.5 }, g);
    mk("ellipse", { cx: s * 0.5, cy: 0, rx: s * 0.58, ry: s * 0.3, fill: "url(#lobeB)", opacity: 0.5 }, g);
    atom(g, 0, 0, s * 0.07, "n");
  }

  function dOrbital(parent, cx, cy, s) {
    const g = group(parent, cx, cy, 0, "spin-slow");
    [[1, 1], [-1, 1], [-1, -1], [1, -1]].forEach(([sx, sy], i) => {
      const ex = sx * s * 0.34, ey = sy * s * 0.34;
      const deg = (Math.atan2(ey, ex) * 180) / Math.PI;
      mk("ellipse", {
        cx: ex, cy: ey, rx: s * 0.4, ry: s * 0.2,
        fill: i % 2 ? "url(#lobeB)" : "url(#lobeA)", opacity: 0.42,
        transform: `rotate(${deg.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)})`,
      }, g);
    });
    atom(g, 0, 0, s * 0.07, "m");
  }

  function sOrbital(parent, cx, cy, s) {
    const g = group(parent, cx, cy, 0, "");
    mk("circle", { cx: 0, cy: 0, r: s, fill: "url(#glowS)", opacity: 0.6 }, g);
    mk("circle", { cx: 0, cy: 0, r: s * 0.55, class: "reticle-ring" }, g);
    atom(g, 0, 0, s * 0.09, "au");
  }

  const FAR_ATOMS = [
    [120, 520, 14, "m", 0.55], [720, 420, 12, "au", 0.5], [1490, 130, 15, "x", 0.45],
    [980, 930, 13, "n", 0.45], [80, 870, 12, "o", 0.4],
  ];
  const NEAR_ATOMS = [
    [180, 740, 4.5, "au", 0.8], [790, 320, 4, "x", 0.7], [1450, 420, 4.5, "o", 0.75],
    [1500, 140, 3.8, "n", 0.6], [420, 90, 4.2, "m", 0.6], [660, 950, 3.6, "au", 0.55],
    [950, 420, 3.4, "h", 0.5],
  ];

  function buildScene() {
    const far = document.getElementById("layer-far");
    const mid = document.getElementById("layer-mid");
    const near = document.getElementById("layer-near");
    if (!far || !mid || !near) return;
    buildDefs(far);

    // far depth: frameworks and orbitals, soft but still structured
    graphene(far, 260, 200, 46, -8, 8, 6);
    mofGrid(far, 1300, 800, 110, 4, 6, 5);
    dOrbital(far, 1170, 250, 170);
    sOrbital(far, 430, 790, 150);
    pOrbital(far, 830, 120, 130, 25, "spin-slow");
    loneAtoms(far, FAR_ATOMS);

    // mid depth: crystal cells and coordination polyhedra, crisp enough to name
    fccCell(mid, 1300, 460, 170);
    octahedron(mid, 1030, 730, 140, -6);
    tetrahedron(mid, 610, 240, 120, 8);
    helix(mid, 850, 895, 460, -4);

    // near depth: hero specimens floating just under the glass
    glowSpot(near, 520, 460, 160, 0.3);
    glowSpot(near, 1260, 620, 150, 0.3);
    benzene(near, 520, 460, 125, 12);
    perovskite(near, 1260, 620, 310);
    waterCluster(near, 1150, 180, 150, 0);
    biphenyl(near, 870, 660, 58, 14);
    pOrbital(near, 320, 860, 100, -30, "spin-rev");
    loneAtoms(near, NEAR_ATOMS);
  }

  buildScene();

  /* ————— parallax + sheen: the stage slides, the glass refracts ————— */

  (function parallax() {
    if (reduceMotion) return;
    const cfgs = [
      { el: document.getElementById("layer-far"), s: 45, m: 9 },
      { el: document.getElementById("layer-mid"), s: 100, m: 20 },
      { el: document.getElementById("layer-near"), s: 170, m: 34 },
    ].filter((c) => c.el);
    if (!cfgs.length) return;
    let tMx = 0, tMy = 0, mx = 0, my = 0, sy = 0;
    window.addEventListener("pointermove", (e) => {
      tMx = e.clientX / window.innerWidth - 0.5;
      tMy = e.clientY / window.innerHeight - 0.5;
    }, { passive: true });
    const loop = () => {
      sy += ((window.scrollY || 0) - sy) * 0.28;
      mx += (tMx - mx) * 0.06;
      my += (tMy - my) * 0.06;
      const k = Math.tanh(sy / 1600);
      for (const c of cfgs) {
        c.el.style.transform = `translate3d(${(-mx * c.m).toFixed(2)}px, ${(k * c.s - my * c.m * 0.6).toFixed(2)}px, 0)`;
      }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  })();

  /* ————— reveal + counters ————— */

  const reveals = document.querySelectorAll(".reveal");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    reveals.forEach((el) => el.classList.add("is-visible"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          io.unobserve(entry.target);
        });
      },
      { threshold: 0.16, rootMargin: "0px 0px -6% 0px" }
    );
    reveals.forEach((el) => io.observe(el));
  }

  const stats = document.querySelectorAll("[data-count]");

  const animateCount = (el) => {
    const target = Number(el.dataset.count || 0);
    if (!Number.isFinite(target)) return;
    if (reduceMotion) {
      el.textContent = String(target);
      return;
    }
    const duration = 1400;
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      // first rAF timestamp can predate `start`, making eased < 0 — clamp it
      el.textContent = String(Math.max(0, Math.round(target * eased)));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  if (reduceMotion || !("IntersectionObserver" in window)) {
    stats.forEach(animateCount);
  } else {
    const countIo = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          animateCount(entry.target);
          countIo.unobserve(entry.target);
        });
      },
      { threshold: 0.5 }
    );
    stats.forEach((el) => countIo.observe(el));
  }
})();
