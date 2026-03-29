"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useWizardState } from "@/hooks/useWizardState";
import WelcomeScreen from "./WelcomeScreen";
import NameInputScreen from "./NameInputScreen";
import BuildingScreen from "./BuildingScreen";
import ProfileScreen from "./ProfileScreen";
import CompleteScreen from "./CompleteScreen";

const fadeVariants = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
};

export default function Wizard() {
  const { state, next, setUser } = useWizardState();

  const screens = [
    <WelcomeScreen key="welcome" onNext={next} />,
    <NameInputScreen key="name" onSubmit={setUser} />,
    <BuildingScreen key="building" onComplete={next} />,
    <ProfileScreen key="profile" name={state.name} role={state.role} onNext={next} />,
    <CompleteScreen key="complete" name={state.name} />,
  ];

  return (
    <div className="w-full flex items-center justify-center">
      <AnimatePresence mode="wait">
        <motion.div
          key={state.step}
          variants={fadeVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          transition={{ duration: 0.5, ease: "easeInOut" }}
          className="w-full flex items-center justify-center"
        >
          {screens[state.step]}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
