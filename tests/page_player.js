// Runs the page's audio worklets (pointe/ui.html, CAPTURE) on a fake clock for tests/test_playout_gaps.py: the
// `player` gets each chunk of the bot's voice when it arrives, and its output is read 128 frames at a time, as the
// browser does. Prints the gaps: silence inside one reply.
//     node tests/page_player.js <worklet code file> <arrivals json: [[seconds, reply], ...] in order>
const fs = require('fs');
const [code, trace] = [fs.readFileSync(process.argv[2], 'utf8'), JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))];
const RATE = 48000, CHUNK = Math.round(0.04 * RATE), processors = {};
class AudioWorkletProcessor { constructor() { this.port = {postMessage() {}, onmessage: null}; } }
new Function('AudioWorkletProcessor', 'registerProcessor', 'sampleRate', code)(
  AudioWorkletProcessor, (name, cls) => { processors[name] = cls; }, RATE);
const player = new processors.player(), out = new Float32Array(128), first = {}, end = {};
let next = 0, gaps = 0, gapFrames = 0;
const last = Math.ceil((trace[trace.length - 1][0] + 1) * RATE);
for (let frame = 0; frame < last; frame += out.length) {
  while (next < trace.length && trace[next][0] <= frame / RATE) {
    player.port.onmessage({data: new Float32Array(CHUNK).fill(trace[next][1] + 1)});  // each reply's samples say which it is
    next++;
  }
  player.process([], [[out]]);
  for (let k = 0; k < out.length; k++) {
    if (out[k] <= 0) continue;
    const reply = out[k] - 1, at = frame + k;
    if (first[reply] === undefined) first[reply] = at;
    else if (at > end[reply] + 1) { gaps++; gapFrames += at - end[reply] - 1; }
    end[reply] = at;
  }
}
console.log(JSON.stringify({gaps, gap_secs: gapFrames / RATE, first: Object.values(first).map(f => f / RATE)}));
