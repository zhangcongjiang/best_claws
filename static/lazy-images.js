(() => {
  const images = Array.from(document.querySelectorAll("img[data-src]"));
  if (images.length === 0) return;

  const load = (img) => {
    const src = img.getAttribute("data-src");
    if (!src) return;
    img.src = src;
    img.removeAttribute("data-src");
  };

  if (!("IntersectionObserver" in window)) {
    images.forEach(load);
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const img = entry.target;
        load(img);
        io.unobserve(img);
      });
    },
    { rootMargin: "200px 0px", threshold: 0.01 }
  );

  images.forEach((img) => io.observe(img));
})();

