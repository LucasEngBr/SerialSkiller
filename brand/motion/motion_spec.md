# Serial Skiller — especificação de movimento da logo

**História:** investiga → encontra o alvo → confirma → propaga → recomeça.
**Personalidade:** precisa, silenciosa, óptica. Só a luz se move; a geometria é imóvel
(sem rotação, escala ou deformação dos traços).

## Peças (SVG `brand/logo/target-s-animated.svg`)

| Peça | Elemento | Papel |
|---|---|---|
| S superior / inferior | 2 paths (`pathLength=1`): arco + eixo horizontal até o anel interno | trilhos dos reflexos |
| Eixos verticais, hastes externas, anel interno | `#ss-geo` | iluminados pela onda |
| Reflexo | `.ss-head` (cabeça, dash .055) + `.ss-trail` (rastro, dash .24, desfocado) | varredura |
| Energia | cópia desfocada de `#ss-geo` (`.ss-energy`) | "concentração" de luz |
| Ponto | `.ss-dot` (r 14, Cold Crimson) + `.ss-halo` (desfocado) | identificação |
| Onda | `.ss-wave` (borda) + máscara `#ss-wave-mask` sobre `.ss-lit` | propagação óptica |

## Linha do tempo (um relógio de 5 s, `infinite`)

| Tempo | % | Acontecimento | Curva |
|---|---|---|---|
| 0,10–1,50 s | 2–30 | reflexos saem das 2 pontas do S e chegam ao centro | ease-in-out `cubic-bezier(.77,0,.175,1)` |
| 0–1,40 s | 0–28 | energia lavanda cresce (bloom até .5) | ease-in-out |
| 1,50–1,85 s | 30–37 | 1ª piscada (.36 → .95 → .38) | acende ease-out `(.23,1,.32,1)`, apaga `ease` |
| 1,85–2,23 s | 37–44,5 | 2ª piscada, mais intensa (→ 1,0, halo .28) | idem |
| 2,23–2,45 s | 44,5–49 | ativação definitiva, ponto fica aceso | ease-out |
| 2,40–2,90 s | 48–58 | halo expande 1 → 1,55 (opacidade .55) | ease-out |
| 2,80–4,00 s | 56–80 | onda do centro até a borda; ilumina anel, eixos e S | expansão ease-out; opacidade ease-in-out |
| 4,00–4,80 s | 80–96 | ponto e brilhos voltam ao repouso | ease-in-out |
| 4,80–5,00 s | 96–100 | repouso (= estado em 0 s) | — |

Repouso: traços em gradiente cromado lavanda, ponto a 36%.
Loop sem costura: todos os valores em 100% são iguais aos de 0%; a onda volta ao centro em 83%,
enquanto está invisível.

## Regras aplicadas

- Curvas **literais** dentro de cada `@keyframes` (`var()` ali é ignorado pelo Chromium e vira linear).
- Um só relógio para todas as peças → `currentTime`/`?t=` mapeia 1:1 a coreografia.
- Reflexos A e B simétricos (rotação de 180°), simultâneos, como pedido.
- Nada parte ou termina junto por acidente: energia, reflexo e rastro têm janelas deslocadas.
- `prefers-reduced-motion: reduce` → sem animação, logo em repouso com o alvo aceso.
- Halo e onda: transparência gradual + desfoque leve; sem flash branco nem "explosão".

## Verificação

- Quadros-chave renderizados em `motion/frames/` e tira em `motion/motion_strip.png`
  (0 / 0,6 / 1,25 / 1,5 / 1,62 / 1,85 / 2,0 / 2,3 / 2,6 / 3,0 / 3,4 / 3,8 / 4,3 / 4,99 s).
- Costura do loop: quadro 4,99 s ≡ quadro 0 s.
- Vídeo de referência: `motion/logo_motion.mp4` (25 fps, 3 ciclos).
- Página interativa: `motion/logo_motion.html` (reiniciar, câmera lenta, velocidade, `?t=ms`, `?static=1`).
