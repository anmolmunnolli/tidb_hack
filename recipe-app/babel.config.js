module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],   // 👈 use this only
    plugins: [],                      // 👈 remove "expo-router/babel"
  };
};
