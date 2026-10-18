# Third-party notices | إشعارات الأطراف الثالثة

MAWRID distributes the following third-party software and font files with its public site and local demonstration. Each component retains its own copyright and license terms.

يتضمن موقع مورد العام أربع حزم تشغيل مباشرة من `package.json` في الجذر. يسرد هذا الملف إصداراتها الفعلية وإشعاراتها، مع تراخيص الخطوط المرفقة. أدوات البناء وتبعيات التطوير غير الموزعة ليست ضمن هذه القائمة.

## Public site runtime libraries

The public site source is in `web/`; its packaged JavaScript is in `assets/app/`. The versions below match the installed root packages and lockfile used for the distribution.

| Component | Version | Included use | License and retained text |
| --- | --- | --- | --- |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.4.16 | Sanitize rendered project content | `(MPL-2.0 OR Apache-2.0)` in package metadata. Both supplied license texts are retained: [Apache 2.0](assets/licenses/DOMPurify-Apache-2.0.txt), [MPL 2.0](assets/licenses/DOMPurify-MPL-2.0.txt), plus the [package header notice](assets/licenses/DOMPurify-NOTICE.txt). |
| [Marked](https://github.com/markedjs/marked) | 18.1.0 | Render Markdown project documentation | MIT; the complete upstream [license file](assets/licenses/marked-LICENSE.txt) also preserves its Markdown attribution and redistribution notice. |
| [Three.js](https://github.com/mrdoob/three.js) | 0.186.1 | Interactive public-site treatment scene, with OrbitControls, RoomEnvironment and RoundedBoxGeometry from the same package | [MIT license and copyright](assets/licenses/three-MIT.txt). |
| [GSAP](https://gsap.com/) | 3.15.0 | Interface animation, CSSPlugin and ScrollTrigger; ScrollTrigger includes Observer | GreenSock's standard “no charge” license, as named by the installed package: [official terms](https://gsap.com/standard-license). [Retained package notices](assets/licenses/GSAP-NOTICE.txt). |

The root sources import these packages from `web/src/main.js`, `web/src/palm-story.js` and `web/src/process-view.js`. Package submodules listed in the table belong to their respective packages.

### Copyright notices

- **DOMPurify:** `(c) Cure53 and other contributors`, as printed in the distributed package header.
- **Marked:** `Copyright (c) 2018+, MarkedJS (https://github.com/markedjs/)` and `Copyright (c) 2011-2018, Christopher Jeffrey (https://github.com/chjj/)`. The supplied license also retains `Copyright © 2004, John Gruber` for Markdown.
- **Three.js:** `Copyright © 2010-2026 three.js authors`.
- **GSAP:** `Copyright 2008-2026, GreenSock. All rights reserved.` Its core and plugin headers state: `Subject to the terms at https://gsap.com/standard-license`.

GSAP is distributed under the GreenSock terms linked above. The project's MIT license does not replace those terms.

## Fonts

| Font | Retained license | Distribution |
| --- | --- | --- |
| IBM Plex Sans Arabic | SIL Open Font License 1.1; `Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"` | [Public-site notice](assets/fonts/LICENSE-plex-arabic.txt); [local UI notice](mawrid-system/client/assets/fonts/OFL.txt). |
| Manrope | SIL Open Font License 1.1; `Copyright 2018 The Manrope Project Authors (https://github.com/googlefonts/manrope)` | [Public-site notice](assets/fonts/LICENSE-manrope.txt). |

Bundled font files retain the notices in their respective distribution folders, including the operational 3D view and engineering viewer below.

## Packaged operational scene and engineering viewer

These local distributions carry their Three.js MIT and IBM Plex Sans Arabic OFL text beside the compiled assets:

- Operational scene: [Three.js](mawrid-system/client/plant3d/licenses/three-MIT.txt) and [IBM Plex Sans Arabic](mawrid-system/client/plant3d/licenses/IBM-Plex-Arabic-OFL.txt).
- Engineering viewer: [Three.js](mawrid-final/dist/licenses/three-MIT.txt) and [IBM Plex Sans Arabic](mawrid-final/dist/licenses/IBM-Plex-Arabic-OFL.txt).

The main local UI also carries its font license at `mawrid-system/client/assets/fonts/OFL.txt`. Its JavaScript entry bundles local MAWRID source modules; the operational 3D scene is a separate packaged entry.

## Other project material

Datasets, papers, institutional marks and other referenced material retain their owners' rights and source-specific terms. Their references and provenance are documented separately in the project evidence and data documentation. Inclusion of an attribution does not imply endorsement or partnership.
