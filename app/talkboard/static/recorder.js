(() => {
  const params = new URLSearchParams(location.search);
  const TIMESLICE_MS = Number(params.get('timeslice') || 10000);
  const SILENCE_CHECK_MS = Number(params.get('silence_check_ms') || 10000);
  const SILENCE_RMS = 0.005;

  const $ = (id) => document.getElementById(id);
  const startButton = $('start');
  const stopButton = $('stop');

  let talkId = null;
  let recorder = null;
  let streams = [];
  let audioContext = null;
  let wakeLock = null;
  let timers = [];
  let nextIndex = 0;
  let uploaded = 0;
  let uploadChain = Promise.resolve();
  let maxRms = 0;
  let recording = false;

  function show(element, message) {
    element.textContent = message;
    element.hidden = false;
  }

  function setStatus(text) {
    $('status').textContent = text;
  }

  async function uploadWithRetry(index, blob) {
    for (let attempt = 0; ; attempt++) {
      try {
        const response = await fetch(`/api/talks/${talkId}/chunks/${index}`, {
          method: 'PUT',
          headers: { 'content-type': 'application/octet-stream' },
          body: blob,
        });
        if (response.ok) {
          uploaded += 1;
          $('chunks-uploaded').textContent = String(uploaded);
          return;
        }
        if (response.status < 500) {
          throw new Error(`Upload rejected (${response.status})`);
        }
      } catch (error) {
        if (error.message.startsWith('Upload rejected')) throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, Math.min(1000 * 2 ** attempt, 15000)));
    }
  }

  function enqueue(blob) {
    const index = nextIndex++;
    uploadChain = uploadChain.then(() => uploadWithRetry(index, blob));
    uploadChain.catch((error) => show($('error'), error.message));
  }

  function watchLevel(audioStream) {
    const source = audioContext.createMediaStreamSource(audioStream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    timers.push(setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const value of samples) sum += ((value - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / samples.length);
      maxRms = Math.max(maxRms, rms);
      $('level').value = Math.min(1, rms * 5);
    }, 100));
    timers.push(setTimeout(() => {
      if (recording && maxRms < SILENCE_RMS) {
        show($('warning'),
          'The input looks silent. Check the microphone, or that the shared tab is playing sound.');
      }
    }, SILENCE_CHECK_MS));
  }

  async function holdWakeLock() {
    try {
      wakeLock = await navigator.wakeLock.request('screen');
    } catch (error) {
      wakeLock = null;
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (recording && document.visibilityState === 'visible') holdWakeLock();
  });

  window.addEventListener('beforeunload', (event) => {
    if (recording) {
      event.preventDefault();
      event.returnValue = '';
    }
  });

  function release() {
    recording = false;
    timers.forEach((timer) => { clearInterval(timer); clearTimeout(timer); });
    timers = [];
    streams.forEach((stream) => stream.getTracks().forEach((track) => track.stop()));
    streams = [];
    if (audioContext) audioContext.close();
    audioContext = null;
    if (wakeLock) wakeLock.release().catch(() => {});
    wakeLock = null;
    startButton.disabled = false;
    stopButton.disabled = true;
  }

  async function getStream(source) {
    if (source === 'mic') {
      return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
    }
    return navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
  }

  async function start() {
    $('error').hidden = true;
    $('warning').hidden = true;
    startButton.disabled = true;

    // Created inside the click so Chrome lets it run.
    audioContext = new AudioContext();

    const source = document.querySelector('input[name=source]:checked').value;
    let stream;
    try {
      stream = await getStream(source);
    } catch (error) {
      release();
      show($('error'), `Could not start: ${error.message}`);
      return;
    }
    streams.push(stream);
    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
      release();
      show($('error'),
        'No audio was shared. For a Chrome tab, tick "Also share tab audio" in the picker.');
      return;
    }
    const audioStream = new MediaStream(audioTracks);

    const response = await fetch('/api/talks', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        title: $('title').value.trim() || 'Untitled talk',
        source,
        language: $('language').value,
        word_list: $('word-list').value.trim(),
      }),
    });
    if (!response.ok) {
      release();
      show($('error'), `Could not create the talk (${response.status})`);
      return;
    }
    talkId = (await response.json()).id;

    nextIndex = 0;
    uploaded = 0;
    maxRms = 0;
    uploadChain = Promise.resolve();
    $('chunks-uploaded').textContent = '0';

    recorder = new MediaRecorder(audioStream, { mimeType: 'audio/webm;codecs=opus' });
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) enqueue(event.data);
    });
    audioTracks[0].addEventListener('ended', () => {
      if (recording) stop();
    });

    recording = true;
    recorder.start(TIMESLICE_MS);
    watchLevel(audioStream);
    holdWakeLock();
    const startedAt = Date.now();
    timers.push(setInterval(() => {
      const seconds = Math.floor((Date.now() - startedAt) / 1000);
      $('timer').textContent =
        `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    }, 1000));
    setStatus('Recording');
    stopButton.disabled = false;
  }

  async function stop() {
    if (!recording) return;
    stopButton.disabled = true;
    setStatus('Finishing…');
    const stopped = new Promise((resolve) => recorder.addEventListener('stop', resolve, { once: true }));
    recorder.stop();
    await stopped;
    try {
      await uploadChain;
      const response = await fetch(`/api/talks/${talkId}/stop`, { method: 'POST' });
      if (!response.ok) throw new Error(`Stop failed (${response.status})`);
      setStatus(`Saved (talk #${talkId})`);
    } catch (error) {
      setStatus('Stopped with a problem');
      show($('error'), error.message);
    }
    release();
  }

  startButton.addEventListener('click', start);
  stopButton.addEventListener('click', stop);
})();
