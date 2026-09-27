// Creates the checked-in JSONL without an API key or a running web server.
// The Python composer remains the submission contract; this is a portability
// helper for environments where Python has not yet been installed.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (folder, id) => JSON.parse(fs.readFileSync(path.join(root, 'expanded', folder, `${id}.json`), 'utf8'));
const text = value => Array.isArray(value) ? value.filter(Boolean).join(', ') : (value == null ? '' : String(value).replaceAll('_', ' '));
const first = (obj, ...keys) => keys.map(key => text(obj[key])).find(Boolean) || '';
const offer = merchant => text(merchant.offers?.find(item => item.status === 'active')?.title);
const owner = merchant => {
  const name = merchant.identity?.owner_first_name || merchant.identity?.name || 'Merchant';
  return merchant.category_slug === 'dentists' && !name.toLowerCase().startsWith('dr') ? `Dr. ${name}` : name;
};
const location = merchant => [merchant.identity?.locality, merchant.identity?.city].filter(Boolean).join(', ');
const trim = body => body.length <= 320 ? body : `${body.slice(0, 319).replace(/\s+\S*$/, '')}.`;

function customerMessage(merchant, trigger, customer) {
  const p = trigger.payload || {}, name = customer.identity?.name?.replace(/\s*\([^)]*\)\s*$/, '') || 'there';
  const business = merchant.identity?.name || owner(merchant), activeOffer = offer(merchant);
  let detail;
  if (trigger.kind.includes('appointment')) detail = `Your appointment is tomorrow${first(p, 'service_due', 'service') ? ` for ${first(p, 'service_due', 'service')}` : ''}.`;
  else if (trigger.kind.includes('refill')) detail = `Your ${first(p, 'molecule_list', 'medicine', 'medication') || 'medicine'} refill is due${first(p, 'stock_runs_out_iso', 'due_date') ? ` before ${first(p, 'stock_runs_out_iso', 'due_date')}` : ''}.`;
  else if (trigger.kind.includes('lapsed')) detail = first(p, 'days_since_last_visit') ? `It has been ${first(p, 'days_since_last_visit')} days since your last visit.` : 'It has been a while since your last visit.';
  else detail = first(p, 'service_due', 'service') ? `Your ${first(p, 'service_due', 'service')} recall is due.` : 'Your follow-up is due.';
  let body = `Hi ${name}, ${business} here. ${detail}`;
  const slots = first(p, 'slots', 'slot_options', 'available_slots');
  if (slots) body += ` Available: ${slots}.`;
  if (activeOffer) body += ` ${activeOffer} is available.`;
  body += ' Reply YES to confirm or share a suitable time.';
  return [body, 'binary_yes_no', 'merchant_on_behalf'];
}

function merchantMessage(category, merchant, trigger) {
  const p = trigger.payload || {}, kind = trigger.kind || 'update', activeOffer = offer(merchant);
  const intro = `${owner(merchant)}${location(merchant) ? ` (${location(merchant)})` : ''},`;
  const digest = category.digest?.find(item => item.id === first(p, 'top_item_id', 'digest_item_id', 'item_id')) || category.digest?.[0] || {};
  let body, cta = 'open_ended';
  if (kind === 'active_planning_intent') body = `${intro} for ${first(p, 'intent_topic') || 'this plan'}, I would start with a clear advance-order offer${activeOffer ? ` built around ${activeOffer}` : ''}. I can draft the post copy, order cutoff and enquiry reply for your approval. Shall I prepare it?`;
  else if (kind.includes('perf_dip')) { body = `${intro} ${first(p, 'metric') || 'performance'}${first(p, 'delta_pct', 'change_pct') ? ` changed ${first(p, 'delta_pct', 'change_pct')}` : ' dipped in the latest window'}.`; if (merchant.performance?.ctr && category.peer_stats?.avg_ctr) body += ` CTR is ${(merchant.performance.ctr * 100).toFixed(1)}% versus peer ${(category.peer_stats.avg_ctr * 100).toFixed(1)}%.`; body += activeOffer ? ` I can refresh a Google post around ${activeOffer}. Want the draft today? YES/STOP` : ' I can draft a focused Google post. Want it today? YES/STOP'; cta = 'binary_yes_no'; }
  else if (kind.includes('perf_spike')) { body = `${intro} ${first(p, 'metric') || 'performance'} is up${first(p, 'delta_pct', 'change_pct') ? ` ${first(p, 'delta_pct', 'change_pct')}` : ' in the latest window'}. ${activeOffer ? `I can extend the momentum with a post around ${activeOffer}.` : 'I can turn the momentum into a fresh post.'} Want me to draft it? YES/STOP`; cta = 'binary_yes_no'; }
  else if (['research_digest', 'regulation_change', 'cde_opportunity', 'category_research_digest_release'].includes(kind) || kind.includes('compliance')) { body = `${intro} ${digest.title || first(p, 'title', 'headline', 'topic') || kind.replaceAll('_', ' ')}.`; if (digest.trial_n) body += ` Evidence base: ${digest.trial_n} participants.`; if (digest.source) body += ` Source: ${digest.source}.`; body += ' Want a short summary and action checklist?'; }
  else if (kind.includes('competitor')) { body = `${intro} ${first(p, 'competitor_name', 'competitor') || 'a competitor'} has opened${first(p, 'distance_km', 'distance') ? ` ${first(p, 'distance_km', 'distance')} away` : ' nearby'}.`; if (activeOffer) body += ` Your ${activeOffer} and existing reviews are the strongest response.`; body += ' Want a comparison-safe Google post draft? YES/STOP'; cta = 'binary_yes_no'; }
  else if (kind.includes('milestone')) { body = `${intro} you reached ${first(p, 'value_now', 'current_value', 'metric_value') || 'a'} ${first(p, 'metric') || 'milestone'}${first(p, 'milestone_value', 'target') ? `; next marker is ${first(p, 'milestone_value', 'target')}` : ''}. Want a ready-to-send review request?`; }
  else if (kind.includes('review_theme') || kind.includes('curious_ask')) { const theme = merchant.review_themes?.[0]?.theme || first(p, 'theme', 'review_theme') || 'customer feedback'; const count = merchant.review_themes?.[0]?.occurrences_30d || first(p, 'review_count', 'occurrences'); body = `${intro} ${count ? `${count} reviews ` : ''}are pointing to ${theme}. Is that the service you want to lead with this week? Reply with one service and I will turn it into a post.`; }
  else if (kind.includes('festival') || kind.includes('seasonal') || kind.includes('ipl') || kind.includes('event') || kind.includes('weather')) { body = `${intro} ${first(p, 'festival', 'event_name', 'match', 'occasion', 'season', 'headline') || kind.replaceAll('_', ' ')} is the timely window.${activeOffer ? ` A single post around ${activeOffer} keeps the message specific.` : ''} Want the draft? YES/STOP`; cta = 'binary_yes_no'; }
  else if (kind.includes('renewal')) body = `${intro} your plan renewal is due${first(p, 'days_remaining', 'days_to_renewal') || merchant.subscription?.days_remaining ? ` in ${first(p, 'days_remaining', 'days_to_renewal') || merchant.subscription.days_remaining} days` : ' soon'}. Want a quick account check before you decide?`;
  else if (kind.includes('dormant') || kind.includes('winback')) { body = `${intro} ${first(p, 'days_since_last_merchant_message', 'days_since_expiry') ? `it has been ${first(p, 'days_since_last_merchant_message', 'days_since_expiry')} days since our last useful update.` : 'I have a concise re-start idea for your listing.'}${activeOffer ? ` I can prepare one recovery post around ${activeOffer}.` : ' I can prepare one recovery post.'} Want the two-line draft? YES/STOP`; cta = 'binary_yes_no'; }
  else if (kind.includes('unverified') || kind.includes('gbp')) body = `${intro} your Google Business Profile still needs verification. I can give you the exact next steps and keep the update checklist ready. Want that?`;
  else body = `${intro} Vera noticed a ${kind.replaceAll('_', ' ')} signal${first(p, 'headline', 'summary', 'intent_topic', 'reason', 'topic', 'metric') ? `: ${first(p, 'headline', 'summary', 'intent_topic', 'reason', 'topic', 'metric')}` : ''}.${activeOffer ? ` I can turn it into a customer-ready update around ${activeOffer}.` : ''} Want the draft?`;
  return [body, cta, 'vera'];
}

const pairs = JSON.parse(fs.readFileSync(path.join(root, 'expanded', 'test_pairs.json'), 'utf8')).pairs;
const rows = pairs.map(pair => {
  const merchant = read('merchants', pair.merchant_id), category = read('categories', merchant.category_slug), trigger = read('triggers', pair.trigger_id), customer = pair.customer_id ? read('customers', pair.customer_id) : null;
  const [body, cta, send_as] = customer || trigger.scope === 'customer' ? customerMessage(merchant, trigger, customer || {}) : merchantMessage(category, merchant, trigger);
  return { test_id: pair.test_id, body: trim(body), cta, send_as, suppression_key: trigger.suppression_key || `${trigger.kind}:${trigger.id}`, rationale: `${trigger.kind.replaceAll('_', ' ')} message composed from the supplied live contexts without invented offers or links.` };
});
fs.writeFileSync(path.join(root, 'submission.jsonl'), rows.map(row => JSON.stringify(row)).join('\n') + '\n');
console.log(`Wrote ${rows.length} deterministic submission rows.`);
