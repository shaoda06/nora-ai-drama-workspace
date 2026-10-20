// Run with an existing cua_repl tab on a scene containing the record link.
// await verifyMarkdownImagePreview(tab, { recordLink, imageLink, dimensions });
// Only clicks preview links and Close; never writes projects or starts generation.
import assert from 'node:assert/strict';

export async function verifyMarkdownImagePreview(tab, { recordLink, imageLink, dimensions }) {
  await tab.playwright.getByRole('link', { name: recordLink, exact: true }).click();
  let dialog = tab.playwright.getByRole('dialog');
  await dialog.getByRole('heading', { name: recordLink, exact: true }).waitFor({ state: 'visible' });
  await dialog.getByRole('link', { name: imageLink, exact: true }).last().click();
  dialog = tab.playwright.getByRole('dialog');
  const image = dialog.getByRole('img', { name: imageLink, exact: true });
  await image.waitFor({ state: 'visible', timeoutMs: 5000 });
  // Visible means the img exists; wait for the local PNG's actual load as well.
  let actual;
  const deadline = Date.now() + 5000;
  do {
    await tab.getAXState({ emit: false });
    actual = await image.evaluate(element => ({
      width: element.naturalWidth, height: element.naturalHeight, loaded: element.complete,
    }));
  } while (!actual.loaded && Date.now() < deadline);
  assert.equal(actual.loaded, true);
  assert.deepEqual([actual.width, actual.height], dimensions);
  assert.ok(!(await dialog.innerText()).includes('资料读取失败'));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  // Image routing must not break the original Markdown preview flow.
  await tab.playwright.getByRole('link', { name: recordLink, exact: true }).click();
  dialog = tab.playwright.getByRole('dialog');
  await dialog.getByRole('heading', { name: '1. 当前正式资产', exact: true }).waitFor({ state: 'visible' });
  assert.ok((await dialog.innerText()).includes('审阅区'));
  assert.ok(!(await dialog.innerText()).includes('资料读取失败'));
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  return { imageLink, ...actual, markdownPreview: 'passed' };
}
