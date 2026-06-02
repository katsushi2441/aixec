<?php
$vwork_promo_variant = isset($vwork_promo_variant) ? $vwork_promo_variant : 'banner';
?>
<?php if ($vwork_promo_variant === 'links'): ?>
<a href="https://exbridge.jp/seminar.html" target="_blank" rel="noopener">セミナー</a>
<a href="https://exbridge.jp/vwork.html" target="_blank" rel="noopener">VWork</a>
<a href="https://katsushi2441.github.io/vwork/" target="_blank" rel="noopener">VWork Blog</a>
<?php else: ?>
<style>
.vwork-promo{background:#0f172a;color:#fff;border-bottom:1px solid rgba(255,255,255,.12)}
.vwork-promo-inner{max-width:1100px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:14px}
.vwork-promo-copy{min-width:0}
.vwork-promo-kicker{font-size:12px;color:#a7f3d0;font-weight:800;margin-bottom:2px}
.vwork-promo-title{font-size:15px;font-weight:800;line-height:1.5}
.vwork-promo-text{font-size:12px;line-height:1.6;color:#dbeafe;margin-top:2px}
.vwork-promo-links{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;flex-shrink:0}
.vwork-promo-links a{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:7px 11px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:800;border:1px solid rgba(255,255,255,.22);color:#fff;background:rgba(255,255,255,.08);white-space:nowrap}
.vwork-promo-links a.primary{background:#22c55e;border-color:#22c55e;color:#052e16}
@media(max-width:720px){.vwork-promo-inner{align-items:flex-start;flex-direction:column}.vwork-promo-links{justify-content:flex-start;width:100%;overflow-x:auto;flex-wrap:nowrap}.vwork-promo-links a{flex-shrink:0}}
</style>
<section class="vwork-promo" aria-label="バイブコーディング導線">
  <div class="vwork-promo-inner">
    <div class="vwork-promo-copy">
      <div class="vwork-promo-kicker">Built with Vibe Coding</div>
      <div class="vwork-promo-title">AIxEC / AIxTube / AIxSNSは、バイブコーディングで制作されています。</div>
      <div class="vwork-promo-text">エクスブリッジは、セミナーとVWorkで業務システム・Web制作の内製化を支援します。</div>
    </div>
    <div class="vwork-promo-links">
      <a class="primary" href="https://exbridge.jp/vwork.html" target="_blank" rel="noopener">VWork</a>
      <a href="https://exbridge.jp/seminar.html" target="_blank" rel="noopener">セミナー</a>
      <a href="https://katsushi2441.github.io/vwork/" target="_blank" rel="noopener">Blog</a>
    </div>
  </div>
</section>
<?php endif; ?>
