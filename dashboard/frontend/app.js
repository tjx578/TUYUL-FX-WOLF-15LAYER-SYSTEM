async function fetchData(endpoint) {
  const res = await fetch(endpoint, {
    headers: {
      Authorization: "Bearer CHANGE_ME",
    },
  });
  return res.json();
}

async function load() {
  const context = await fetchData("/context");
  const execution = await fetchData("/execution");
  const verdict = await fetchData("/verdict");

  document.getElementById("output").textContent = JSON.stringify(
    { context, execution, verdict },
    null,
    2
  );
}

load();
setInterval(load, 5000);
